import json
from collections import Counter
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, status
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, inspect, or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.runtime_checks import build_runtime_report
from app.core.security import require_papel
from app.db.database import get_db
from app.models.auditoria_evento import AuditoriaEvento
from app.models.papel import Papel
from app.models.papel_permissao import PapelPermissao
from app.models.user import User
from app.services.runtime_observability import get_persisted_http_latency_summary
from app.services import supabase_auth
from app.services.frontend_performance import get_frontend_performance_summary

router = APIRouter()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


PERMISSION_MODULES = [
    {"codigo": "dashboard", "nome": "Dashboard"},
    {"codigo": "agenda", "nome": "Agenda"},
    {"codigo": "logistica", "nome": "Logistica"},
    {"codigo": "pacientes", "nome": "Pacientes e tutores"},
    {"codigo": "clinicas", "nome": "Clinicas"},
    {"codigo": "servicos", "nome": "Servicos"},
    {"codigo": "laudos", "nome": "Laudos"},
    {"codigo": "frases", "nome": "Frases"},
    {"codigo": "referencias_eco", "nome": "Referencias eco"},
    {"codigo": "financeiro", "nome": "Financeiro"},
    {"codigo": "fiscal", "nome": "Fiscal"},
    {"codigo": "relatorios", "nome": "Relatorios"},
    {"codigo": "ordens_servico", "nome": "Ordens de servico"},
    {"codigo": "atendimento_clinico", "nome": "Atendimento clinico"},
    {"codigo": "configuracoes", "nome": "Configuracoes"},
    {"codigo": "usuarios_permissoes", "nome": "Usuarios e permissoes"},
]
PERMISSION_MODULE_CODES = {item["codigo"] for item in PERMISSION_MODULES}
_BCRYPT_PREFIXES = ("$2a$", "$2b$", "$2y$", "$2$")
_DIAGNOSTIC_SAMPLE_LIMIT = 10
_PERMISSION_SEED_ALIASES = {
    "logistica": ("agenda", "clinicas"),
}


class PapelAdminResponse(BaseModel):
    id: int
    nome: str
    descricao: Optional[str] = None


class UsuarioAdminCreate(BaseModel):
    nome: str = Field(..., min_length=2, max_length=120)
    email: EmailStr
    senha: str = Field(..., min_length=6, max_length=200)
    ativo: int = 1
    papeis: List[str] = Field(default_factory=list)


class UsuarioAdminUpdate(BaseModel):
    nome: Optional[str] = Field(default=None, min_length=2, max_length=120)
    email: Optional[EmailStr] = None
    senha: Optional[str] = Field(default=None, min_length=6, max_length=200)
    ativo: Optional[int] = None
    papeis: Optional[List[str]] = None


class PermissaoItemUpdate(BaseModel):
    papel_id: int
    modulo: str
    visualizar: bool
    editar: bool
    excluir: bool


class PermissoesUpdatePayload(BaseModel):
    itens: List[PermissaoItemUpdate] = Field(default_factory=list)


def _serializar_usuario(user: User) -> dict:
    papeis = sorted((p.nome for p in user.papeis), key=lambda nome: nome.lower())
    return {
        "id": user.id,
        "nome": user.nome,
        "email": user.email,
        "ativo": user.ativo,
        "papeis": papeis,
        "criado_em": user.criado_em,
        "ultimo_acesso": user.ultimo_acesso,
    }


def _hash_senha(senha: str) -> str:
    # bcrypt considera apenas os primeiros 72 bytes.
    senha_truncada = senha.encode("utf-8")[:72].decode("utf-8", errors="ignore")
    return pwd_context.hash(senha_truncada)


def _resolver_papeis(db: Session, nomes_papeis: List[str]) -> List[Papel]:
    nomes_normalizados = sorted(
        {
            (nome or "").strip().lower()
            for nome in nomes_papeis
            if (nome or "").strip()
        }
    )
    if not nomes_normalizados:
        return []

    papeis = db.query(Papel).all()
    papeis_por_nome = {(papel.nome or "").strip().lower(): papel for papel in papeis}

    faltantes = [nome for nome in nomes_normalizados if nome not in papeis_por_nome]
    if faltantes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Papel(es) invalido(s): {', '.join(faltantes)}",
        )

    return [papeis_por_nome[nome] for nome in nomes_normalizados]


def _default_permission_flags(nome_papel: str, modulo: str) -> Tuple[int, int, int]:
    papel = (nome_papel or "").strip().lower()
    if papel == "admin":
        return 1, 1, 1
    if modulo == "dashboard":
        return 1, 0, 0
    return 0, 0, 0


def _derive_permission_flags_from_aliases(
    papel_id: int,
    modulo: str,
    permission_map: Dict[Tuple[int, str], Tuple[int, int, int]],
) -> Optional[Tuple[int, int, int]]:
    aliases = _PERMISSION_SEED_ALIASES.get(modulo, ())
    if not aliases:
        return None

    collected = [
        permission_map[(papel_id, alias)]
        for alias in aliases
        if (papel_id, alias) in permission_map
    ]
    if not collected:
        return None

    visualizar = 1 if any(item[0] for item in collected) else 0
    editar = 1 if any(item[1] for item in collected) else 0
    excluir = 1 if any(item[2] for item in collected) else 0
    return visualizar, editar, excluir


def _garantir_matriz_permissoes(db: Session) -> List[Papel]:
    _sync_permission_matrix(db, commit=True)
    return db.query(Papel).order_by(Papel.nome.asc()).all()


def _sync_permission_matrix(
    db: Session,
    *,
    modules: Optional[Set[str]] = None,
    commit: bool,
) -> dict:
    invalid_modules = sorted(
        modulo for modulo in (modules or set())
        if modulo not in PERMISSION_MODULE_CODES
    )
    if invalid_modules:
        raise ValueError(f"Modulo(s) invalido(s): {', '.join(invalid_modules)}")

    papeis = db.query(Papel).order_by(Papel.nome.asc()).all()
    papeis_por_id = {papel.id: papel for papel in papeis}
    permissoes_existentes = db.query(PapelPermissao).all()
    mapa_existente: Set[Tuple[int, str]] = {
        (perm.papel_id, (perm.modulo or "").strip())
        for perm in permissoes_existentes
    }
    permission_values: Dict[Tuple[int, str], Tuple[int, int, int]] = {
        (perm.papel_id, (perm.modulo or "").strip()): (
            int(perm.visualizar or 0),
            int(perm.editar or 0),
            int(perm.excluir or 0),
        )
        for perm in permissoes_existentes
    }

    selected_modules = sorted(modules or PERMISSION_MODULE_CODES)
    created_rows: List[dict] = []

    for papel in papeis:
        for modulo in selected_modules:
            chave = (papel.id, modulo)
            if chave in mapa_existente:
                continue

            derived_flags = _derive_permission_flags_from_aliases(
                papel.id,
                modulo,
                permission_values,
            )
            if derived_flags is not None:
                visualizar, editar, excluir = derived_flags
                source = "alias"
                aliases = list(_PERMISSION_SEED_ALIASES.get(modulo, ()))
            else:
                visualizar, editar, excluir = _default_permission_flags(papel.nome, modulo)
                source = "default"
                aliases = []

            if commit:
                db.add(
                    PapelPermissao(
                        papel_id=papel.id,
                        modulo=modulo,
                        visualizar=visualizar,
                        editar=editar,
                        excluir=excluir,
                    )
                )

            created_rows.append(
                {
                    "papel_id": papel.id,
                    "papel_nome": papel.nome,
                    "modulo": modulo,
                    "visualizar": bool(visualizar),
                    "editar": bool(editar),
                    "excluir": bool(excluir),
                    "source": source,
                    "aliases": aliases,
                }
            )
            mapa_existente.add(chave)
            permission_values[chave] = (visualizar, editar, excluir)

    if commit and created_rows:
        db.commit()

    created_by_module = Counter(item["modulo"] for item in created_rows)
    return {
        "commit_applied": bool(commit),
        "target_modules": selected_modules,
        "roles_count": len(papeis),
        "permission_rows_before": len(permissoes_existentes),
        "created_count": len(created_rows),
        "created_by_module": dict(sorted(created_by_module.items())),
        "created_rows": created_rows,
        "created_rows_sample": created_rows[:20],
        "roles": [
            {"id": papel_id, "nome": papeis_por_id[papel_id].nome}
            for papel_id in sorted(papeis_por_id)
        ],
    }


def _serializar_usuario_risco(user: User) -> dict:
    return {
        "id": user.id,
        "nome": user.nome,
        "email": user.email,
        "ativo": bool(user.ativo),
    }


def _is_bcrypt_hash(value: Optional[str]) -> bool:
    raw = str(value or "").strip()
    return raw.startswith(_BCRYPT_PREFIXES)


def _avaliar_secret_key(runtime_report: dict) -> dict:
    details = dict(runtime_report.get("security", {}).get("secret_key") or {})
    blockers: List[str] = []
    if not details.get("configured"):
        blockers.append("SECRET_KEY nao configurada.")
    if not details.get("strong"):
        blockers.append(details.get("warning") or "SECRET_KEY nao atende ao minimo recomendado.")

    return {
        "current_value": bool(settings.REQUIRE_STRONG_SECRET_KEY),
        "safe_to_enable": len(blockers) == 0,
        "blockers": blockers,
        "details": {
            "configured": bool(details.get("configured")),
            "strong": bool(details.get("strong")),
            "warning": details.get("warning"),
        },
    }


def _avaliar_migracoes(runtime_report: dict) -> dict:
    details = dict(runtime_report.get("migrations") or {})
    blockers: List[str] = []
    if not details.get("tracking_table_exists"):
        blockers.append("Tabela schema_migrations ausente.")
    if int(details.get("pending_count") or 0) > 0:
        blockers.append(f"{details['pending_count']} migracao(oes) pendente(s).")
    if details.get("unknown_applied_versions"):
        blockers.append("Existem versoes aplicadas fora do codigo atual.")

    return {
        "current_value": bool(settings.REQUIRE_UP_TO_DATE_MIGRATIONS),
        "safe_to_enable": len(blockers) == 0,
        "blockers": blockers,
        "details": {
            "tracking_table_exists": bool(details.get("tracking_table_exists")),
            "current_version": details.get("current_version"),
            "latest_version": details.get("latest_version"),
            "pending_count": int(details.get("pending_count") or 0),
            "pending_versions": details.get("pending_versions") or [],
            "unknown_applied_versions": details.get("unknown_applied_versions") or [],
        },
    }


def _avaliar_senhas_legadas(db: Session) -> dict:
    usuarios = db.query(User).order_by(User.id.asc()).all()
    bcrypt_count = 0
    usuarios_legados: List[dict] = []
    usuarios_sem_hash: List[dict] = []

    for usuario in usuarios:
        senha_hash = str(usuario.senha_hash or "").strip()
        if not senha_hash:
            usuarios_sem_hash.append(_serializar_usuario_risco(usuario))
            continue
        if _is_bcrypt_hash(senha_hash):
            bcrypt_count += 1
            continue
        usuarios_legados.append(_serializar_usuario_risco(usuario))

    blockers: List[str] = []
    if usuarios_legados:
        blockers.append(f"{len(usuarios_legados)} usuario(s) ainda usam senha legada.")
    if usuarios_sem_hash:
        blockers.append(f"{len(usuarios_sem_hash)} usuario(s) estao sem senha_hash valido.")

    sample = (usuarios_legados + usuarios_sem_hash)[:_DIAGNOSTIC_SAMPLE_LIMIT]
    return {
        "current_value": bool(settings.ALLOW_LEGACY_PLAIN_PASSWORDS),
        "safe_to_disable": len(blockers) == 0,
        "blockers": blockers,
        "details": {
            "total_users": len(usuarios),
            "bcrypt_users": bcrypt_count,
            "legacy_users_count": len(usuarios_legados),
            "users_without_hash_count": len(usuarios_sem_hash),
            "affected_users_sample": sample,
        },
    }


def _avaliar_fallback_permissoes(db: Session) -> dict:
    inspector = inspect(db.bind)
    table_names = set(inspector.get_table_names())
    permissions_table_exists = "papeis_permissoes" in table_names
    roles_table_exists = "papeis" in table_names
    user_role_table_exists = "usuario_papel" in table_names

    papeis = db.query(Papel).order_by(Papel.nome.asc()).all() if roles_table_exists else []
    permission_rows = db.query(PapelPermissao).all() if permissions_table_exists else []

    permission_map: Dict[int, Set[str]] = {}
    unknown_modules: Set[str] = set()
    for registro in permission_rows:
        modulo = (registro.modulo or "").strip()
        permission_map.setdefault(registro.papel_id, set()).add(modulo)
        if modulo and modulo not in PERMISSION_MODULE_CODES:
            unknown_modules.add(modulo)

    incomplete_roles: List[dict] = []
    for papel in papeis:
        missing_modules = [
            modulo for modulo in sorted(PERMISSION_MODULE_CODES)
            if modulo not in permission_map.get(papel.id, set())
        ]
        if missing_modules:
            incomplete_roles.append(
                {
                    "papel_id": papel.id,
                    "papel_nome": papel.nome,
                    "usuarios_vinculados": len(papel.usuarios) if user_role_table_exists else None,
                    "missing_modules": missing_modules,
                }
            )

    users_without_roles_count = None
    users_without_roles_sample: List[dict] = []
    if user_role_table_exists:
        users_without_roles_count = db.query(User).filter(~User.papeis.any()).count()
        users_without_roles = (
            db.query(User)
            .filter(~User.papeis.any())
            .order_by(User.id.asc())
            .limit(_DIAGNOSTIC_SAMPLE_LIMIT)
            .all()
        )
        users_without_roles_sample = [_serializar_usuario_risco(user) for user in users_without_roles]

    blockers: List[str] = []
    if not permissions_table_exists:
        blockers.append("Tabela papeis_permissoes ausente.")
    if incomplete_roles:
        blockers.append(f"{len(incomplete_roles)} papel(is) sem cobertura completa de modulos.")
    if unknown_modules:
        blockers.append("Existem modulos desconhecidos na matriz de permissoes.")

    return {
        "current_value": bool(settings.ALLOW_PERMISSION_MATRIX_FALLBACK),
        "safe_to_disable": len(blockers) == 0,
        "blockers": blockers,
        "details": {
            "permissions_table_exists": permissions_table_exists,
            "roles_table_exists": roles_table_exists,
            "user_role_table_exists": user_role_table_exists,
            "roles_count": len(papeis),
            "permission_rows_count": len(permission_rows),
            "expected_modules_count": len(PERMISSION_MODULE_CODES),
            "unknown_modules": sorted(unknown_modules),
            "incomplete_roles_count": len(incomplete_roles),
            "incomplete_roles_sample": incomplete_roles[:_DIAGNOSTIC_SAMPLE_LIMIT],
            "missing_modules_summary": dict(
                sorted(
                    Counter(
                        modulo
                        for item in incomplete_roles
                        for modulo in item["missing_modules"]
                    ).items()
                )
            ),
            "users_without_roles_count": users_without_roles_count,
            "users_without_roles_sample": users_without_roles_sample,
        },
    }


def _montar_checklist_rollout(checks: dict) -> dict:
    return {
        "principios": [
            "Aplicar no maximo uma flag por deploy.",
            "Validar /health, /ready e este endpoint antes do proximo passo.",
            "Promover para producao somente o que ficou verde em stage.",
        ],
        "stage": [
            {
                "ordem": 1,
                "acao": "Deploy desta versao em stage sem alterar flags e observar os checks.",
                "liberado": True,
            },
            {
                "ordem": 2,
                "flag": "REQUIRE_UP_TO_DATE_MIGRATIONS",
                "acao": "Ativar REQUIRE_UP_TO_DATE_MIGRATIONS=true em stage.",
                "liberado": bool(checks["REQUIRE_UP_TO_DATE_MIGRATIONS"]["safe_to_enable"]),
                "bloqueios": checks["REQUIRE_UP_TO_DATE_MIGRATIONS"]["blockers"],
            },
            {
                "ordem": 3,
                "flag": "ALLOW_PERMISSION_MATRIX_FALLBACK",
                "acao": "Desativar ALLOW_PERMISSION_MATRIX_FALLBACK em stage.",
                "liberado": bool(checks["ALLOW_PERMISSION_MATRIX_FALLBACK"]["safe_to_disable"]),
                "bloqueios": checks["ALLOW_PERMISSION_MATRIX_FALLBACK"]["blockers"],
            },
            {
                "ordem": 4,
                "flag": "ALLOW_LEGACY_PLAIN_PASSWORDS",
                "acao": "Desativar ALLOW_LEGACY_PLAIN_PASSWORDS em stage.",
                "liberado": bool(checks["ALLOW_LEGACY_PLAIN_PASSWORDS"]["safe_to_disable"]),
                "bloqueios": checks["ALLOW_LEGACY_PLAIN_PASSWORDS"]["blockers"],
            },
            {
                "ordem": 5,
                "flag": "REQUIRE_STRONG_SECRET_KEY",
                "acao": "Ativar REQUIRE_STRONG_SECRET_KEY=true em stage.",
                "liberado": bool(checks["REQUIRE_STRONG_SECRET_KEY"]["safe_to_enable"]),
                "bloqueios": checks["REQUIRE_STRONG_SECRET_KEY"]["blockers"],
            },
        ],
        "producao": [
            {
                "ordem": 1,
                "acao": "Replicar em producao apenas as flags que ficaram estaveis em stage.",
                "liberado": True,
            },
            {
                "ordem": 2,
                "acao": "Manter a mesma ordem e validar uma unica flag por deploy.",
                "liberado": True,
            },
        ],
    }

@router.get("/dashboard")
def admin_dashboard(current_user: User = Depends(require_papel("admin"))):
    return {
        "message": "Bem-vindo ao painel de admin",
        "user": current_user.nome,
        "papeis": [p.nome for p in current_user.papeis],
    }


@router.get("/hardening-readiness")
def obter_hardening_readiness(
    current_user: User = Depends(require_papel("admin")),
    db: Session = Depends(get_db),
):
    _ = current_user
    runtime_report = build_runtime_report()
    checks = {
        "REQUIRE_UP_TO_DATE_MIGRATIONS": _avaliar_migracoes(runtime_report),
        "REQUIRE_STRONG_SECRET_KEY": _avaliar_secret_key(runtime_report),
        "ALLOW_LEGACY_PLAIN_PASSWORDS": _avaliar_senhas_legadas(db),
        "ALLOW_PERMISSION_MATRIX_FALLBACK": _avaliar_fallback_permissoes(db),
    }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "runtime": {
            "status": runtime_report.get("status"),
            "ready": bool(runtime_report.get("ready")),
            "warnings": runtime_report.get("warnings") or [],
            "readiness_issues": runtime_report.get("readiness_issues") or [],
            "environment": runtime_report.get("environment") or {},
            "observability": runtime_report.get("observability") or {},
        },
        "flags": {
            "APP_ENV": str(settings.APP_ENV or "").strip() or "development",
            "ENFORCE_STRONG_SECRET_KEY_IN_PRODUCTION": bool(
                settings.ENFORCE_STRONG_SECRET_KEY_IN_PRODUCTION
            ),
            "REQUIRE_UP_TO_DATE_MIGRATIONS": bool(settings.REQUIRE_UP_TO_DATE_MIGRATIONS),
            "REQUIRE_STRONG_SECRET_KEY": bool(settings.REQUIRE_STRONG_SECRET_KEY),
            "ALLOW_LEGACY_PLAIN_PASSWORDS": bool(settings.ALLOW_LEGACY_PLAIN_PASSWORDS),
            "ALLOW_PERMISSION_MATRIX_FALLBACK": bool(settings.ALLOW_PERMISSION_MATRIX_FALLBACK),
        },
        "checks": checks,
        "rollout_checklist": _montar_checklist_rollout(checks),
    }


@router.get("/observability/http-latency")
def obter_latencia_http_persistida(
    hours: int = Query(default=24, ge=1, le=168),
    current_user: User = Depends(require_papel("admin")),
    db: Session = Depends(get_db),
):
    """Resumo de performance por prefixo e release, restrito a administradores."""

    _ = current_user
    return get_persisted_http_latency_summary(db, hours=hours)


@router.get("/observability/frontend-performance")
def obter_desempenho_frontend_persistido(
    hours: int = Query(default=24, ge=1, le=168),
    current_user: User = Depends(require_papel("admin")),
    db: Session = Depends(get_db),
):
    """Resumo RUM por rota e release, sem amostras individuais ou identidade."""

    _ = current_user
    return get_frontend_performance_summary(db, hours=hours)


@router.get("/papeis", response_model=List[PapelAdminResponse])
def listar_papeis(
    current_user: User = Depends(require_papel("admin")),
    db: Session = Depends(get_db),
):
    _ = current_user
    papeis = db.query(Papel).order_by(Papel.nome.asc()).all()
    return [
        {"id": papel.id, "nome": papel.nome, "descricao": papel.descricao}
        for papel in papeis
    ]


@router.get("/permissoes")
def listar_permissoes(
    current_user: User = Depends(require_papel("admin")),
    db: Session = Depends(get_db),
):
    _ = current_user
    papeis = _garantir_matriz_permissoes(db)

    permissoes = db.query(PapelPermissao).all()
    por_chave: Dict[Tuple[int, str], PapelPermissao] = {
        (perm.papel_id, perm.modulo): perm for perm in permissoes
    }

    payload_papeis = []
    for papel in papeis:
        permissoes_papel = []
        for modulo in PERMISSION_MODULES:
            codigo = modulo["codigo"]
            registro = por_chave.get((papel.id, codigo))
            if registro is None:
                visualizar, editar, excluir = _default_permission_flags(papel.nome, codigo)
                permissoes_papel.append(
                    {
                        "modulo": codigo,
                        "visualizar": bool(visualizar),
                        "editar": bool(editar),
                        "excluir": bool(excluir),
                    }
                )
            else:
                permissoes_papel.append(
                    {
                        "modulo": codigo,
                        "visualizar": bool(registro.visualizar),
                        "editar": bool(registro.editar),
                        "excluir": bool(registro.excluir),
                    }
                )

        payload_papeis.append(
            {
                "id": papel.id,
                "nome": papel.nome,
                "descricao": papel.descricao,
                "permissoes": permissoes_papel,
            }
        )

    return {"modulos": PERMISSION_MODULES, "papeis": payload_papeis}


@router.put("/permissoes")
def atualizar_permissoes(
    payload: PermissoesUpdatePayload,
    current_user: User = Depends(require_papel("admin")),
    db: Session = Depends(get_db),
):
    _ = current_user
    if not payload.itens:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nenhuma permissao enviada.",
        )

    papeis = db.query(Papel).all()
    papel_ids = {papel.id for papel in papeis}

    permissoes_existentes = db.query(PapelPermissao).all()
    por_chave: Dict[Tuple[int, str], PapelPermissao] = {
        (perm.papel_id, perm.modulo): perm for perm in permissoes_existentes
    }

    for item in payload.itens:
        modulo = (item.modulo or "").strip()
        if modulo not in PERMISSION_MODULE_CODES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Modulo invalido: {modulo}",
            )

        if item.papel_id not in papel_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Papel invalido: {item.papel_id}",
            )

        chave = (item.papel_id, modulo)
        registro = por_chave.get(chave)
        if registro is None:
            registro = PapelPermissao(papel_id=item.papel_id, modulo=modulo)
            db.add(registro)
            por_chave[chave] = registro

        registro.visualizar = 1 if item.visualizar else 0
        registro.editar = 1 if item.editar else 0
        registro.excluir = 1 if item.excluir else 0

    db.commit()
    return {"message": "Permissoes atualizadas com sucesso.", "total": len(payload.itens)}


@router.post("/permissoes/sync")
def sincronizar_permissoes(
    dry_run: bool = True,
    modulos: Optional[List[str]] = Query(default=None),
    current_user: User = Depends(require_papel("admin")),
    db: Session = Depends(get_db),
):
    _ = current_user
    modulos_normalizados = {
        (modulo or "").strip()
        for modulo in (modulos or [])
        if (modulo or "").strip()
    } or None

    try:
        summary = _sync_permission_matrix(
            db,
            modules=modulos_normalizados,
            commit=not dry_run,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return {
        "dry_run": bool(dry_run),
        **summary,
    }


@router.get("/usuarios")
def listar_usuarios(
    current_user: User = Depends(require_papel("admin")),
    db: Session = Depends(get_db),
):
    _ = current_user
    usuarios = db.query(User).order_by(User.nome.asc()).all()
    return [_serializar_usuario(usuario) for usuario in usuarios]


@router.post("/usuarios", status_code=status.HTTP_201_CREATED)
def criar_usuario(
    payload: UsuarioAdminCreate,
    current_user: User = Depends(require_papel("admin")),
    db: Session = Depends(get_db),
):
    _ = current_user
    email_normalizado = payload.email.strip().lower()
    existente = db.query(User).filter(func.lower(User.email) == email_normalizado).first()
    if existente:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ja existe um usuario com este e-mail.",
        )

    papeis = _resolver_papeis(db, payload.papeis)

    novo_usuario = User(
        nome=payload.nome.strip(),
        email=email_normalizado,
        senha_hash=_hash_senha(payload.senha),
        ativo=1 if payload.ativo else 0,
        criado_por=current_user.id,
        tentativas_login=0,
        bloqueado_ate=None,
    )
    novo_usuario.papeis = papeis

    db.add(novo_usuario)
    if settings.AUTH_PROVIDER == "supabase":
        # Obtain the local ID before provisioning; no user metadata controls it.
        db.flush()
        supabase_auth.create_identity(novo_usuario, password=payload.senha)
    db.commit()
    db.refresh(novo_usuario)
    return _serializar_usuario(novo_usuario)


@router.put("/usuarios/{usuario_id}")
def atualizar_usuario(
    usuario_id: int,
    payload: UsuarioAdminUpdate,
    current_user: User = Depends(require_papel("admin")),
    db: Session = Depends(get_db),
):
    usuario = db.query(User).filter(User.id == usuario_id).first()
    if not usuario:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario nao encontrado.",
        )

    if payload.nome is not None:
        usuario.nome = payload.nome.strip()

    if payload.email is not None:
        email_normalizado = payload.email.strip().lower()
        existente = (
            db.query(User)
            .filter(func.lower(User.email) == email_normalizado, User.id != usuario_id)
            .first()
        )
        if existente:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Ja existe outro usuario com este e-mail.",
            )
        usuario.email = email_normalizado

    if payload.ativo is not None:
        if current_user.id == usuario_id and payload.ativo == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Nao e permitido desativar o proprio usuario.",
            )
        usuario.ativo = 1 if payload.ativo else 0

    if payload.senha:
        usuario.senha_hash = _hash_senha(payload.senha)

    if payload.papeis is not None:
        papeis = _resolver_papeis(db, payload.papeis)
        usuario.papeis = papeis

    if settings.AUTH_PROVIDER == "supabase" and (payload.email is not None or payload.senha):
        supabase_auth.update_identity(usuario, password=payload.senha)

    db.commit()
    db.refresh(usuario)
    return _serializar_usuario(usuario)


@router.delete("/usuarios/{usuario_id}")
def desativar_usuario(
    usuario_id: int,
    current_user: User = Depends(require_papel("admin")),
    db: Session = Depends(get_db),
):
    usuario = db.query(User).filter(User.id == usuario_id).first()
    if not usuario:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario nao encontrado.",
        )

    if current_user.id == usuario_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nao e permitido desativar o proprio usuario.",
        )

    usuario.ativo = 0
    db.commit()
    return {"message": "Usuario desativado com sucesso.", "id": usuario_id, "ativo": 0}


@router.get("/auditoria")
def listar_auditoria(
    modulo: Optional[str] = None,
    acao: Optional[str] = None,
    entidade: Optional[str] = None,
    busca: Optional[str] = None,
    data_inicio: Optional[str] = None,
    data_fim: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(require_papel("admin")),
    db: Session = Depends(get_db),
):
    _ = current_user
    if "auditoria_eventos" not in inspect(db.bind).get_table_names():
        return {"total": 0, "items": [], "modulos": [], "acoes": []}

    query = db.query(AuditoriaEvento)

    if modulo:
        query = query.filter(AuditoriaEvento.modulo == modulo.strip())
    if acao:
        query = query.filter(AuditoriaEvento.acao == acao.strip())
    if entidade:
        query = query.filter(AuditoriaEvento.entidade == entidade.strip())

    if busca:
        termo = f"%{busca.strip()}%"
        query = query.filter(
            or_(
                AuditoriaEvento.usuario_nome.ilike(termo),
                AuditoriaEvento.usuario_email.ilike(termo),
                AuditoriaEvento.descricao.ilike(termo),
                AuditoriaEvento.entidade_id.ilike(termo),
            )
        )

    if data_inicio:
        query = query.filter(func.date(AuditoriaEvento.created_at) >= data_inicio)
    if data_fim:
        query = query.filter(func.date(AuditoriaEvento.created_at) <= data_fim)

    total = query.count()
    rows = (
        query.order_by(AuditoriaEvento.created_at.desc(), AuditoriaEvento.id.desc())
        .offset(skip)
        .limit(max(1, min(limit, 500)))
        .all()
    )

    modulos = [row[0] for row in db.query(AuditoriaEvento.modulo).distinct().order_by(AuditoriaEvento.modulo.asc()).all()]
    acoes = [row[0] for row in db.query(AuditoriaEvento.acao).distinct().order_by(AuditoriaEvento.acao.asc()).all()]

    def _parse_detalhes(raw: Optional[str]) -> dict:
        if not raw:
            return {}
        try:
            value = json.loads(raw)
            return value if isinstance(value, dict) else {"raw": value}
        except Exception:
            return {"raw": raw}

    def _format_created_at(value: Optional[datetime]) -> Optional[str]:
        if not isinstance(value, datetime):
            return str(value) if value is not None else None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc).isoformat()
        return value.astimezone(timezone.utc).isoformat()

    items = [
        {
            "id": row.id,
            "created_at": _format_created_at(row.created_at),
            "usuario_id": row.usuario_id,
            "usuario_nome": row.usuario_nome,
            "usuario_email": row.usuario_email,
            "modulo": row.modulo,
            "entidade": row.entidade,
            "entidade_id": row.entidade_id,
            "acao": row.acao,
            "descricao": row.descricao,
            "detalhes": _parse_detalhes(row.detalhes_json),
            "ip_origem": row.ip_origem,
            "rota": row.rota,
            "metodo": row.metodo,
        }
        for row in rows
    ]

    return {
        "total": total,
        "items": items,
        "modulos": modulos,
        "acoes": acoes,
    }

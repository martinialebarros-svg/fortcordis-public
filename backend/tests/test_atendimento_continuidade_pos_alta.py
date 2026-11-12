"""Continuidade pos-alta: adendo clinico e receita multipla por atendimento.

Cenario que originou a spec `atendimento-continuidade-pos-alta`: o paciente e
atendido e o atendimento e finalizado; dias depois o tutor manda o exame
solicitado e o vet precisa anexar o resultado e emitir uma receita
complementar, sem criar um encontro novo e sem sobrescrever o que ja foi
entregue.
"""
import asyncio
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from io import BytesIO
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException, UploadFile
from sqlalchemy import create_engine, event
from starlette.datastructures import Headers
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "atendimento-continuidade-test-secret-key-1234567890")

from app.api.v1.endpoints import atendimento
from app.models.agendamento import Agendamento
from app.models.auditoria_evento import AuditoriaEvento
from app.models.atendimento_clinico import (
    AlertaClinico,
    AnexoAtendimento,
    AtendimentoClinico,
    DocumentoAtendimento,
    EvolucaoClinica,
    ExameAjuste,
    Medicamento,
    PrescricaoClinica,
    PrescricaoItem,
    PrescricaoItemAjuste,
)
from app.models.clinica import Clinica
from app.models.laudo import Exame, Laudo
from app.models.ordem_servico import OrdemServico
from app.models.paciente import Paciente
from app.models.servico import Servico
from app.models.tabela_preco import PrecoServico, PrecoServicoClinica
from app.models.tutor import Tutor
from app.schemas.atendimento import (
    AdendoPayload,
    AtendimentoFinalizarPayload,
    AtendimentoUpdatePayload,
    PrescricaoComplementarPayload,
    PrescricaoItemPayload,
    PrescricaoPayload,
    PrescricaoSyncPayload,
)


class AtendimentoContinuidadePosAltaTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tmpdir.name) / "continuidade-pos-alta.db"
        self.engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False},
        )
        for table in (
            Tutor.__table__,
            Paciente.__table__,
            Clinica.__table__,
            Servico.__table__,
            PrecoServico.__table__,
            PrecoServicoClinica.__table__,
            Agendamento.__table__,
            AtendimentoClinico.__table__,
            OrdemServico.__table__,
            Exame.__table__,
            ExameAjuste.__table__,
            Laudo.__table__,
            AnexoAtendimento.__table__,
            EvolucaoClinica.__table__,
            PrescricaoClinica.__table__,
            PrescricaoItem.__table__,
            PrescricaoItemAjuste.__table__,
            DocumentoAtendimento.__table__,
            AlertaClinico.__table__,
            Medicamento.__table__,
            AuditoriaEvento.__table__,
        ):
            table.create(self.engine, checkfirst=True)
        self.db = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)()
        self.user = SimpleNamespace(id=17, nome="Dra. Teste", email="teste@example.com")
        self.request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/v1/atendimentos/1/adendos",
                "headers": [],
                "client": ("127.0.0.1", 1234),
                "server": ("testserver", 80),
                "scheme": "http",
                "query_string": b"",
            }
        )

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()
        self.tmpdir.cleanup()

    # === seeds ===

    def _seed_atendimento_finalizado(self, *, com_exame_solicitado=True):
        """Atendimento agendado, atendido e finalizado - com OS gerada."""
        tutor = Tutor(nome="Tutora Teste", ativo=1)
        paciente = Paciente(nome="Rex", especie="Canina", tutor_id=None, ativo=1, peso_kg=12.0)
        clinica = Clinica(nome="Clinica Teste", tabela_preco_id=1)
        servico = Servico(
            nome="Consulta",
            preco=Decimal("150.00"),
            preco_fortaleza_comercial=Decimal("150.00"),
            preco_fortaleza_plantao=Decimal("220.00"),
        )
        self.db.add_all([tutor, paciente, clinica, servico])
        self.db.flush()
        paciente.tutor_id = tutor.id

        agendamento = Agendamento(
            paciente_id=paciente.id,
            tutor_id=tutor.id,
            clinica_id=clinica.id,
            servico_id=servico.id,
            origem_atendimento="clinica_parceira",
            inicio=datetime(2026, 9, 1, 14, 30),
            status="Em atendimento",
        )
        self.db.add(agendamento)
        self.db.flush()

        registro = AtendimentoClinico(
            paciente_id=paciente.id,
            tutor_id=tutor.id,
            clinica_id=clinica.id,
            agendamento_id=agendamento.id,
            veterinario_id=self.user.id,
            especie=paciente.especie,
            data_atendimento=agendamento.inicio,
            status="Em atendimento",
            queixa_principal="Tosse ha uma semana.",
            exame_fisico="Sopro grau III.",
            diagnostico_principal="Suspeita de cardiopatia.",
            plano_terapeutico="Aguardar ecocardiograma.",
            criado_por_id=self.user.id,
            criado_por_nome=self.user.nome,
        )
        self.db.add(registro)
        self.db.flush()

        exame = None
        if com_exame_solicitado:
            exame = Exame(
                atendimento_id=registro.id,
                paciente_id=paciente.id,
                tipo_exame="Ecocardiograma",
                status="Solicitado",
            )
            self.db.add(exame)

        prescricao = PrescricaoClinica(
            atendimento_id=registro.id,
            sequencia=1,
            orientacoes_gerais="Repouso ate o resultado.",
            retorno_dias=7,
        )
        self.db.add(prescricao)
        self.db.flush()
        self.db.add(
            PrescricaoItem(
                prescricao_id=prescricao.id,
                medicamento_nome="Furosemida",
                dose="2 mg/kg",
                frequencia="12/12h",
                duracao="7 dias",
                via="Oral",
                ordem=0,
            )
        )
        self.db.commit()

        with (
            patch.object(atendimento, "_emitir_efeitos_finalizacao"),
            patch.object(
                atendimento,
                "_montar_detalhe_atendimento",
                side_effect=lambda _db, item: {"id": item.id, "status": item.status},
            ),
        ):
            atendimento.finalizar_atendimento(
                registro.id,
                AtendimentoFinalizarPayload(tipo_horario="comercial"),
                self.request,
                db=self.db,
                current_user=self.user,
            )

        self.db.refresh(registro)
        self.db.refresh(agendamento)
        if exame is not None:
            self.db.refresh(exame)
        self.db.refresh(prescricao)
        return SimpleNamespace(
            atendimento=registro,
            agendamento=agendamento,
            paciente=paciente,
            exame=exame,
            prescricao=prescricao,
        )

    def _criar_adendo(self, atendimento_id, *, tipo="resultado_exame", descricao="Exame recebido pelo tutor."):
        with patch.object(atendimento, "registrar_auditoria") as auditoria:
            resposta = atendimento.criar_adendo(
                atendimento_id,
                AdendoPayload(tipo=tipo, descricao=descricao),
                self.request,
                db=self.db,
                current_user=self.user,
            )
        return resposta["adendo"], auditoria

    async def _upload_no_adendo(self, atendimento_id, *, exame_id, evolucao_id):
        arquivo = UploadFile(
            filename="eco.pdf",
            file=BytesIO(b"%PDF-conteudo-do-exame"),
            headers=Headers({"content-type": "application/pdf"}),
        )
        with (
            patch.object(
                atendimento,
                "store_atendimento_attachment_file",
                return_value=("/tmp/eco.pdf", "eco.pdf", "application/pdf"),
            ),
            patch.object(atendimento, "_registrar_upload_dedupe_metrica"),
        ):
            return await atendimento.upload_anexo(
                atendimento_id=atendimento_id,
                arquivo=arquivo,
                tipo="documento",
                descricao="Exame enviado pelo tutor.",
                exame_id=exame_id,
                evolucao_id=evolucao_id,
                db=self.db,
                current_user=self.user,
            )

    def _itens_da_receita(self, prescricao_id):
        return (
            self.db.query(PrescricaoItem)
            .filter(PrescricaoItem.prescricao_id == prescricao_id)
            .order_by(PrescricaoItem.ordem.asc(), PrescricaoItem.id.asc())
            .all()
        )

    # === CA-001 / RF-001, RF-002, RF-004, RF-005, RF-006 ===

    def test_adendo_anexa_exame_recebido_depois_sem_criar_atendimento(self) -> None:
        ctx = self._seed_atendimento_finalizado()
        atendimentos_antes = self.db.query(AtendimentoClinico).count()

        adendo, auditoria = self._criar_adendo(ctx.atendimento.id)

        self.assertEqual(adendo["tipo"], "resultado_exame")
        self.assertEqual(adendo["pos_conclusao"], 1)
        self.assertEqual(auditoria.call_args.kwargs["acao"], "CRIAR_ADENDO_POS_CONCLUSAO")

        anexo = asyncio.run(
            self._upload_no_adendo(
                ctx.atendimento.id,
                exame_id=ctx.exame.id,
                evolucao_id=adendo["id"],
            )
        )

        self.assertEqual(anexo["evolucao_id"], adendo["id"])
        self.assertEqual(anexo["exame_id"], ctx.exame.id)
        # Mesmo episodio: nenhum atendimento novo foi criado.
        self.assertEqual(self.db.query(AtendimentoClinico).count(), atendimentos_antes)

        self.db.refresh(ctx.exame)
        # RF-005: sem regra nova - o arquivo tira o exame de "Solicitado" pelas
        # mesmas regras de hoje; "Concluido" continua exigindo o resultado
        # interpretado.
        self.assertEqual(ctx.exame.status, "Em andamento")
        self.assertEqual(
            atendimento._derivar_status_exame(
                status_atual=ctx.exame.status,
                resultado="Insuficiencia mitral leve.",
                total_anexos=1,
            ),
            "Concluido",
        )

        detalhe = atendimento._montar_detalhe_atendimento(self.db, ctx.atendimento)
        self.assertEqual(len(detalhe["adendos"]), 1)
        self.assertEqual(len(detalhe["adendos"][0]["anexos"]), 1)

    def test_pos_conclusao_e_derivado_no_backend(self) -> None:
        ctx = self._seed_atendimento_finalizado(com_exame_solicitado=False)
        ctx.atendimento.status = "Em atendimento"
        self.db.commit()

        adendo, auditoria = self._criar_adendo(ctx.atendimento.id, tipo="evolucao")

        # Atendimento em andamento: evolucao comum, sem auditoria de adendo.
        self.assertEqual(adendo["pos_conclusao"], 0)
        auditoria.assert_not_called()

    # === CA-002 / RF-011, RF-012 ===

    def test_receita_complementar_preserva_a_receita_do_dia(self) -> None:
        ctx = self._seed_atendimento_finalizado()
        itens_originais = {
            item.id: (item.medicamento_nome, item.dose, item.frequencia)
            for item in self._itens_da_receita(ctx.prescricao.id)
        }
        adendo, _ = self._criar_adendo(ctx.atendimento.id, tipo="receita_complementar")

        with patch.object(atendimento, "registrar_auditoria"):
            resposta = atendimento.criar_prescricao_complementar(
                ctx.atendimento.id,
                PrescricaoComplementarPayload(
                    adendo_id=adendo["id"],
                    copiar_de_prescricao_id=ctx.prescricao.id,
                ),
                self.request,
                db=self.db,
                current_user=self.user,
            )

        complementar = resposta["prescricao"]
        self.assertEqual(complementar["sequencia"], 2)
        self.assertEqual(complementar["adendo_id"], adendo["id"])
        self.assertEqual(len(complementar["itens"]), 1)
        # Copia, nao emprestimo de id: editar a copia nunca alcanca a original.
        self.assertNotIn(complementar["itens"][0]["id"], itens_originais)

        itens_payload = [
            PrescricaoItemPayload(
                id=complementar["itens"][0]["id"],
                medicamento_nome="Furosemida",
                dose="3 mg/kg",
                frequencia="8/8h",
                duracao="10 dias",
                via="Oral",
                ordem=0,
            ),
            PrescricaoItemPayload(
                medicamento_nome="Pimobendana",
                dose="0,25 mg/kg",
                frequencia="12/12h",
                duracao="Continuo",
                via="Oral",
                ordem=1,
            ),
        ]
        with patch.object(atendimento, "registrar_auditoria"):
            atualizada = atendimento.atualizar_prescricao(
                ctx.atendimento.id,
                complementar["id"],
                PrescricaoSyncPayload(
                    orientacoes_gerais="Ajuste apos o ecocardiograma.",
                    itens=itens_payload,
                ),
                self.request,
                db=self.db,
                current_user=self.user,
            )

        self.assertEqual(len(atualizada["prescricao"]["itens"]), 2)
        # A receita do dia continua exatamente como foi entregue.
        itens_depois = {
            item.id: (item.medicamento_nome, item.dose, item.frequencia)
            for item in self._itens_da_receita(ctx.prescricao.id)
        }
        self.assertEqual(itens_depois, itens_originais)
        self.db.refresh(ctx.prescricao)
        self.assertEqual(ctx.prescricao.orientacoes_gerais, "Repouso ate o resultado.")

    # === CA-003 / RF-015, RF-016 ===

    def test_pdf_da_receita_do_dia_nao_muda_depois_da_complementar(self) -> None:
        ctx = self._seed_atendimento_finalizado()
        capturas = []

        def _fake_pdf(_atendimento, _paciente, _tutor, _clinica, prescricao, itens, **_kwargs):
            capturas.append(
                (
                    prescricao.id,
                    prescricao.orientacoes_gerais,
                    [(item.medicamento_nome, item.dose, item.frequencia) for item in itens],
                )
            )
            return b"%PDF-fake"

        with (
            patch.object(atendimento, "_autenticar_usuario_pdf", return_value=self.user),
            patch.object(
                atendimento,
                "_obter_branding_pdf_documento",
                return_value={
                    "nome_veterinario": "Dra. Teste",
                    "crmv": "CRMV 1",
                    "logomarca_bytes": None,
                    "assinatura_bytes": None,
                    "texto_rodape": "",
                },
            ),
            patch.object(atendimento, "_gerar_pdf_prescricao_bytes", side_effect=_fake_pdf),
            patch.object(atendimento, "registrar_auditoria"),
        ):
            atendimento.gerar_pdf_prescricao(ctx.atendimento.id, self.request, db=self.db)
            self.db.refresh(ctx.prescricao)
            emitida_primeira = ctx.prescricao.emitida_em
            self.assertIsNotNone(emitida_primeira)

            adendo, _ = self._criar_adendo(ctx.atendimento.id, tipo="receita_complementar")
            complementar = atendimento.criar_prescricao_complementar(
                ctx.atendimento.id,
                PrescricaoComplementarPayload(
                    adendo_id=adendo["id"],
                    copiar_de_prescricao_id=ctx.prescricao.id,
                ),
                self.request,
                db=self.db,
                current_user=self.user,
            )["prescricao"]
            atendimento.atualizar_prescricao(
                ctx.atendimento.id,
                complementar["id"],
                PrescricaoSyncPayload(
                    orientacoes_gerais="Conduta nova.",
                    itens=[
                        PrescricaoItemPayload(
                            id=complementar["itens"][0]["id"],
                            medicamento_nome="Furosemida",
                            dose="3 mg/kg",
                            frequencia="8/8h",
                            ordem=0,
                        )
                    ],
                ),
                self.request,
                db=self.db,
                current_user=self.user,
            )
            atendimento.gerar_pdf_prescricao(ctx.atendimento.id, self.request, db=self.db)

        self.assertEqual(capturas[0], capturas[1])
        self.db.refresh(ctx.prescricao)
        # Emissao e marcada uma unica vez.
        self.assertEqual(ctx.prescricao.emitida_em, emitida_primeira)

    # === CA-004 / RF-013, RF-014 ===

    def test_editar_receita_emitida_sem_confirmacao_preserva_emissao_e_audita(self) -> None:
        ctx = self._seed_atendimento_finalizado()
        ctx.prescricao.emitida_em = datetime(2026, 9, 1, 15, 0)
        self.db.commit()
        item = self._itens_da_receita(ctx.prescricao.id)[0]

        payload_alterado = dict(
            orientacoes_gerais="Repouso ate o resultado.",
            retorno_dias=7,
            itens=[
                PrescricaoItemPayload(
                    id=item.id,
                    medicamento_nome="Furosemida",
                    dose="4 mg/kg",
                    frequencia="12/12h",
                    duracao="7 dias",
                    via="Oral",
                    ordem=0,
                )
            ],
        )

        with patch.object(atendimento, "registrar_auditoria") as auditoria:
            atendimento.atualizar_prescricao(
                ctx.atendimento.id,
                ctx.prescricao.id,
                PrescricaoSyncPayload(
                    **payload_alterado
                ),
                self.request,
                db=self.db,
                current_user=self.user,
            )

        self.db.refresh(item)
        self.assertEqual(item.dose, "4 mg/kg")
        acoes = [chamada.kwargs["acao"] for chamada in auditoria.call_args_list]
        self.assertIn("EDITAR_RECEITA_EMITIDA", acoes)
        evento = next(c.kwargs for c in auditoria.call_args_list if c.kwargs["acao"] == "EDITAR_RECEITA_EMITIDA")
        self.assertEqual(evento["detalhes"]["alteracoes"]["itens"]["antes"][0]["dose"], "2 mg/kg")
        self.assertEqual(evento["detalhes"]["alteracoes"]["itens"]["depois"][0]["dose"], "4 mg/kg")
        self.assertEqual(ctx.prescricao.emitida_em, datetime(2026, 9, 1, 15, 0))


    def test_reenvio_sem_mudanca_nao_exige_confirmacao(self) -> None:
        """O autosave reenvia a receita inteira a cada save.

        Sem a comparacao previa, toda digitacao posterior a emissao do PDF
        cairia em 409 e o salvamento do prontuario pararia."""
        ctx = self._seed_atendimento_finalizado()
        ctx.prescricao.emitida_em = datetime(2026, 9, 1, 15, 0)
        self.db.commit()
        item = self._itens_da_receita(ctx.prescricao.id)[0]

        with patch.object(atendimento, "registrar_auditoria") as auditoria:
            resposta = atendimento.atualizar_prescricao(
                ctx.atendimento.id,
                ctx.prescricao.id,
                PrescricaoSyncPayload(
                    orientacoes_gerais="Repouso ate o resultado.",
                    retorno_dias=7,
                    itens=[
                        PrescricaoItemPayload(
                            id=item.id,
                            medicamento_nome="Furosemida",
                            dose="2 mg/kg",
                            frequencia="12/12h",
                            duracao="7 dias",
                            via="Oral",
                            ordem=0,
                        )
                    ],
                ),
                self.request,
                db=self.db,
                current_user=self.user,
            )

        self.assertEqual(resposta["prescricao"]["sequencia"], 1)
        acoes = [chamada.kwargs["acao"] for chamada in auditoria.call_args_list]
        self.assertNotIn("EDITAR_RECEITA_EMITIDA", acoes)

    # === CA-005 / RF-003, NFR-002 ===

    def test_adendo_e_receita_complementar_nao_geram_ordem_de_servico(self) -> None:
        ctx = self._seed_atendimento_finalizado()
        os_antes = self.db.query(OrdemServico).filter_by(agendamento_id=ctx.agendamento.id).count()
        self.assertEqual(os_antes, 1)

        adendo, _ = self._criar_adendo(ctx.atendimento.id, tipo="receita_complementar")
        with patch.object(atendimento, "registrar_auditoria"):
            atendimento.criar_prescricao_complementar(
                ctx.atendimento.id,
                PrescricaoComplementarPayload(adendo_id=adendo["id"]),
                self.request,
                db=self.db,
                current_user=self.user,
            )

        self.db.refresh(ctx.agendamento)
        self.db.refresh(ctx.atendimento)
        self.assertEqual(
            self.db.query(OrdemServico).filter_by(agendamento_id=ctx.agendamento.id).count(),
            1,
        )
        self.assertEqual(ctx.agendamento.status, "Realizado")
        self.assertEqual(ctx.atendimento.status, "Concluido")

    # === CA-006 / RF-008 ===

    def test_timeline_mostra_adendo_no_mesmo_episodio(self) -> None:
        ctx = self._seed_atendimento_finalizado()
        self._criar_adendo(ctx.atendimento.id)

        grupos = atendimento._montar_timeline_paciente(self.db, ctx.paciente.id)
        eventos = [evento for grupo in grupos for evento in grupo["eventos"]]
        evolucoes = [evento for evento in eventos if evento["tipo"] == "evolucao"]
        atendimentos_timeline = [evento for evento in eventos if evento["tipo"] == "atendimento"]

        self.assertEqual(len(evolucoes), 1)
        self.assertEqual(evolucoes[0]["subtipo"], "resultado_exame")
        self.assertEqual(evolucoes[0]["pos_conclusao"], 1)
        self.assertEqual(evolucoes[0]["titulo"], "Resultado de exame recebido")
        # Um unico encontro na timeline, nao dois.
        self.assertEqual(len(atendimentos_timeline), 1)

    # === CA-008 / RF-017, RF-018, NFR-003 ===

    def test_contrato_legado_da_prescricao_preservado(self) -> None:
        ctx = self._seed_atendimento_finalizado()
        adendo, _ = self._criar_adendo(ctx.atendimento.id, tipo="receita_complementar")
        with patch.object(atendimento, "registrar_auditoria"):
            atendimento.criar_prescricao_complementar(
                ctx.atendimento.id,
                PrescricaoComplementarPayload(
                    adendo_id=adendo["id"],
                    copiar_de_prescricao_id=ctx.prescricao.id,
                ),
                self.request,
                db=self.db,
                current_user=self.user,
            )

        detalhe = atendimento._montar_detalhe_atendimento(self.db, ctx.atendimento)
        # A chave legada continua apontando para a receita do dia.
        self.assertEqual(detalhe["prescricao"]["id"], ctx.prescricao.id)
        self.assertEqual(detalhe["prescricao"]["sequencia"], 1)
        self.assertEqual([item["sequencia"] for item in detalhe["prescricoes"]], [1, 2])
        for chave in ("orientacoes_gerais", "retorno_dias", "peso_referencia_kg", "itens", "apoio_clinico"):
            self.assertIn(chave, detalhe["prescricao"])

    def test_put_do_atendimento_continua_sincronizando_a_receita_do_dia(self) -> None:
        ctx = self._seed_atendimento_finalizado()
        adendo, _ = self._criar_adendo(ctx.atendimento.id, tipo="receita_complementar")
        with patch.object(atendimento, "registrar_auditoria"):
            complementar = atendimento.criar_prescricao_complementar(
                ctx.atendimento.id,
                PrescricaoComplementarPayload(adendo_id=adendo["id"]),
                self.request,
                db=self.db,
                current_user=self.user,
            )["prescricao"]

        item = self._itens_da_receita(ctx.prescricao.id)[0]
        with patch.object(atendimento, "registrar_auditoria"):
            atendimento.atualizar_atendimento(
                ctx.atendimento.id,
                AtendimentoUpdatePayload(
                    prescricao=PrescricaoPayload(
                        orientacoes_gerais="Correcao de digitacao.",
                        itens=[
                            PrescricaoItemPayload(
                                id=item.id,
                                medicamento_nome="Furosemida",
                                dose="2 mg/kg",
                                frequencia="12/12h",
                                duracao="7 dias",
                                via="Oral",
                                ordem=0,
                            )
                        ],
                    )
                ),
                db=self.db,
                current_user=self.user,
                request=self.request,
            )

        self.db.refresh(ctx.prescricao)
        self.assertEqual(ctx.prescricao.orientacoes_gerais, "Correcao de digitacao.")
        # A complementar nao foi tocada pelo caminho legado.
        complementar_db = self.db.query(PrescricaoClinica).filter_by(id=complementar["id"]).one()
        self.assertEqual(complementar_db.orientacoes_gerais, "")
        self.assertEqual(complementar_db.sequencia, 2)

    # === RF-010, RF-019 ===

    def test_sequencia_e_unica_por_atendimento(self) -> None:
        ctx = self._seed_atendimento_finalizado()
        self.db.add(PrescricaoClinica(atendimento_id=ctx.atendimento.id, sequencia=1))
        with self.assertRaises(Exception):
            self.db.commit()
        self.db.rollback()

    def test_exclusao_remove_todas_as_receitas_e_adendos(self) -> None:
        ctx = self._seed_atendimento_finalizado()
        adendo, _ = self._criar_adendo(ctx.atendimento.id, tipo="receita_complementar")
        with patch.object(atendimento, "registrar_auditoria"):
            atendimento.criar_prescricao_complementar(
                ctx.atendimento.id,
                PrescricaoComplementarPayload(
                    adendo_id=adendo["id"],
                    copiar_de_prescricao_id=ctx.prescricao.id,
                ),
                self.request,
                db=self.db,
                current_user=self.user,
            )
        self.assertEqual(self.db.query(PrescricaoClinica).count(), 2)

        with (
            patch.object(atendimento, "registrar_auditoria"),
            patch.object(atendimento, "desfazer_recebimento_ordem"),
        ):
            atendimento.excluir_atendimento(
                ctx.atendimento.id,
                self.request,
                confirmar_exclusao=True,
                db=self.db,
                current_user=self.user,
            )

        self.assertEqual(self.db.query(PrescricaoClinica).count(), 0)
        self.assertEqual(self.db.query(PrescricaoItem).count(), 0)
        self.assertEqual(self.db.query(EvolucaoClinica).count(), 0)

    # === NFR-004 ===

    def _contar_queries_do_detalhe(self, registro):
        statements = []

        def _capture_sql(_conn, _cursor, statement, _parameters, _context, _executemany):
            statements.append(statement.lower())

        event.listen(self.engine, "before_cursor_execute", _capture_sql)
        try:
            detalhe = atendimento._montar_detalhe_atendimento(self.db, registro)
        finally:
            event.remove(self.engine, "before_cursor_execute", _capture_sql)

        por_tabela = {
            "prescricoes_clinicas": len([q for q in statements if "from prescricoes_clinicas" in q]),
            "prescricoes_itens": len([q for q in statements if "from prescricoes_itens" in q]),
            "prescricao_item_ajustes": len(
                [q for q in statements if "from prescricao_item_ajustes" in q]
            ),
            "medicamentos": len([q for q in statements if "from medicamentos" in q]),
        }
        return detalhe, por_tabela

    def test_detalhe_carrega_varias_receitas_sem_n_mais_1(self) -> None:
        ctx = self._seed_atendimento_finalizado()
        # A linha de base ja tem um adendo: o objetivo e isolar o custo das
        # receitas, nao o de existir adendo.
        self._criar_adendo(ctx.atendimento.id, tipo="orientacao")

        detalhe_uma, queries_uma = self._contar_queries_do_detalhe(ctx.atendimento)
        self.assertEqual(len(detalhe_uma["prescricoes"]), 1)

        with patch.object(atendimento, "registrar_auditoria"):
            for _ in range(3):
                adendo = atendimento.criar_adendo(
                    ctx.atendimento.id,
                    AdendoPayload(tipo="receita_complementar", descricao="Ajuste de conduta."),
                    self.request,
                    db=self.db,
                    current_user=self.user,
                )["adendo"]
                atendimento.criar_prescricao_complementar(
                    ctx.atendimento.id,
                    PrescricaoComplementarPayload(
                        adendo_id=adendo["id"],
                        copiar_de_prescricao_id=ctx.prescricao.id,
                    ),
                    self.request,
                    db=self.db,
                    current_user=self.user,
                )

        detalhe_varias, queries_varias = self._contar_queries_do_detalhe(ctx.atendimento)
        self.assertEqual(len(detalhe_varias["prescricoes"]), 4)
        # O custo das receitas nao acompanha a quantidade delas.
        self.assertEqual(queries_uma, queries_varias)
        self.assertEqual(queries_varias["prescricoes_itens"], 1)

    # === Spec receita-emitida-em-fuso-operacional ===
    #
    # A coluna nasceu como TIMESTAMP naive enquanto o modelo declarava
    # timezone=True. Em Postgres isso fazia o valor aware virar UTC na
    # gravacao, e `_to_iso` entregava sem offset - o frontend, que le string
    # sem fuso como horario operacional, mostrava 3h a frente.
    #
    # Os dois testes injetam um datetime aware em UTC, que e o que o Postgres
    # devolve depois da migracao 20260911_84. Injetar direto e proposital: em
    # SQLite a ida ao banco descarta o offset e guarda os numeros locais, entao
    # um teste que dependesse do round trip passaria mesmo com o defeito vivo.

    def test_emitida_em_e_servido_em_horario_operacional(self) -> None:
        ctx = self._seed_atendimento_finalizado()
        # Mesmo instante do registro que ficou torto em producao: 03:44 UTC,
        # ou seja 00:44 no horario operacional.
        ctx.prescricao.emitida_em = datetime(
            2026, 9, 11, 3, 44, 46, tzinfo=timezone.utc
        )

        detalhe = atendimento._montar_detalhe_atendimento(self.db, ctx.atendimento)
        receita_do_dia = next(p for p in detalhe["prescricoes"] if p["sequencia"] == 1)

        self.assertEqual(receita_do_dia["emitida_em"], "2026-09-11T00:44:46-03:00")

    def test_historico_da_receita_emitida_usa_hora_local(self) -> None:
        ctx = self._seed_atendimento_finalizado()
        ctx.prescricao.emitida_em = datetime(
            2026, 9, 11, 3, 44, 46, tzinfo=timezone.utc
        )
        antes = atendimento._snapshot_prescricao(self.db, ctx.prescricao)
        ctx.prescricao.orientacoes_gerais = "Conduta nova."
        with patch.object(atendimento, "registrar_auditoria") as auditoria:
            atendimento._auditar_edicao_prescricao(
                self.db, current_user=self.user, atendimento=ctx.atendimento,
                prescricao=ctx.prescricao, antes=antes, request=self.request,
            )

        detalhes = next(c.kwargs["detalhes"] for c in auditoria.call_args_list
                        if c.kwargs["acao"] == "EDITAR_RECEITA_EMITIDA")
        self.assertEqual(detalhes["emitida_em"], "2026-09-11T00:44:46-03:00")



if __name__ == "__main__":
    unittest.main()

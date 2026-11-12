import asyncio
import io
import json
import os
import sys
import tempfile
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from starlette.datastructures import UploadFile, Headers
from starlette.requests import Request

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "eletro-ordem-test-secret-key-1234567890")

from app.api.v1.endpoints import laudos, ordens_servico
from app.db.database import Base
from app.models.agendamento import Agendamento
from app.models.atendimento_clinico import AnexoAtendimento
from app.models.auditoria_evento import AuditoriaEvento
from app.models.clinica import Clinica
from app.models.laudo import Laudo
from app.models.ordem_servico import OrdemServico
from app.models.paciente import Paciente
from app.models.servico import Servico
from app.models.tabela_preco import PrecoServicoClinica
from app.services import laudo_ordem_servico_service as service


PDF = b"%PDF-1.4\nECG ficticio para teste\n"


class LaudoEletroOrdemServicoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_engine(f"sqlite:///{self.tmp.name}/test.db", connect_args={"check_same_thread": False})
        Base.metadata.create_all(self.engine)
        self.session = sessionmaker(bind=self.engine, autoflush=False)
        self.db = self.session()
        self.user = SimpleNamespace(id=7, nome="Veterinario Teste", email="test@example.com", tem_papel=lambda name: name == "admin")
        self.db.add_all([
            Paciente(id=1, nome="Pet teste", ativo=1),
            Clinica(id=1, nome="Clinica teste", ativo=True, tabela_preco_id=1),
            Servico(id=1, nome="Laudo de eletrocardiograma", ativo=True,
                    preco_fortaleza_comercial=100, preco_fortaleza_plantao=160),
            PrecoServicoClinica(clinica_id=1, servico_id=1, ativo=1, preco_comercial=Decimal("75.50")),
        ])
        self.db.commit()
        self.store = patch.object(laudos, "store_atendimento_attachment_file", side_effect=self._store)
        self.store_mock = self.store.start()

    def tearDown(self):
        self.store.stop()
        self.db.close()
        self.engine.dispose()
        self.tmp.cleanup()

    def _store(self, atendimento_id, filename, content, content_type):
        path = Path(self.tmp.name) / f"{uuid.uuid4()}.pdf"
        path.write_bytes(content)
        return str(path), filename, content_type

    def upload(self, *, db=None, content=PDF, **overrides):
        args = dict(arquivo=UploadFile(io.BytesIO(content), filename="eletro.pdf", headers=Headers({"content-type": "application/pdf"})),
            agendamento_id=None, atendimento_id=None, paciente_id=1, clinic_id=1,
            veterinario_parceiro_id=None, data_exame="2026-10-05", observacoes="",
            gerar_ordem_servico=True, servico_id=1, tipo_horario="comercial",
            idempotency_key="envio-teste-123", db=db or self.db, current_user=self.user)
        args.update(overrides)
        return asyncio.run(laudos.criar_laudo_eletrocardiograma_por_pdf(**args))

    def request(self):
        return Request({"type": "http", "method": "DELETE", "path": "/api/v1/laudos/1", "headers": []})

    def test_upload_cria_os_pendente_com_preco_negociado_sem_agenda_e_auditoria(self):
        response = self.upload()
        self.assertEqual(response["ordem_servico"]["valor_final"], 75.5)
        self.assertEqual(response["ordem_servico"]["status"], "Pendente")
        ordem = self.db.query(OrdemServico).one()
        laudo = self.db.query(Laudo).one()
        self.assertEqual(ordem.laudo_id, laudo.id)
        self.assertEqual(ordem.numero_os, f"OS-LAUDO-{laudo.id}")
        self.assertIsNone(ordem.agendamento_id)
        self.assertIsNone(laudo.agendamento_id)
        self.assertEqual(self.db.query(Agendamento).count(), 0)
        self.assertEqual(ordem.data_atendimento, laudo.data_exame)
        self.assertTrue(Path(self.db.query(AnexoAtendimento).one().caminho_arquivo).is_file())
        audit = self.db.query(AuditoriaEvento).one()
        self.assertEqual(audit.usuario_id, 7)
        self.assertEqual(json.loads(audit.detalhes_json)["laudo_id"], laudo.id)
        detail = laudos.obter_laudo(laudo.id, self.db, self.user)
        self.assertEqual(detail["ordem_servico"], response["ordem_servico"])
        self.assertEqual(ordens_servico._serialize_os(ordem)["laudo_id"], laudo.id)

    def test_sem_opcao_preserva_upload_sem_criar_cobranca(self):
        response = self.upload(gerar_ordem_servico=False, servico_id=None, idempotency_key=None)
        self.assertIsNone(response["ordem_servico"])
        self.assertEqual(self.db.query(Laudo).count(), 1)
        self.assertEqual(self.db.query(OrdemServico).count(), 0)
        self.assertEqual(self.db.query(AuditoriaEvento).count(), 0)

    def test_preview_e_upload_aplicam_mesmo_preco_de_plantao(self):
        preview = laudos.preview_ordem_servico_eletrocardiograma(1, 1, "plantao", self.db, self.user)
        response = self.upload(tipo_horario="plantao")
        self.assertEqual(preview["valor_final"], 160)
        self.assertEqual(preview["valor_final"], response["ordem_servico"]["valor_final"])

    def test_retry_reutiliza_laudo_os_anexo_auditoria_sem_recalcular(self):
        first = self.upload()
        preco = self.db.query(PrecoServicoClinica).one()
        preco.preco_comercial = 99
        self.db.commit()
        second = self.upload()
        self.assertEqual(first, second)
        self.assertEqual(self.db.query(OrdemServico).count(), 1)
        self.assertEqual(self.db.query(Laudo).count(), 1)
        self.assertEqual(self.db.query(AnexoAtendimento).count(), 1)
        self.assertEqual(self.db.query(AuditoriaEvento).count(), 1)
        self.assertEqual(self.store_mock.call_count, 1)

    def test_mesma_chave_com_outro_pdf_ou_dados_rejeita(self):
        self.upload()
        for override in ({"content": PDF + b"alterado"}, {"tipo_horario": "plantao"}, {"data_exame": "2026-10-04"}):
            with self.subTest(override=override), self.assertRaises(HTTPException) as caught:
                self.upload(**override)
            self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(self.db.query(OrdemServico).count(), 1)

    def test_validacoes_nao_persistem_arquivo_laudo_ou_os(self):
        for override in ({"clinic_id": None}, {"clinic_id": 999}, {"servico_id": None}, {"servico_id": 999},
                         {"tipo_horario": "invalido"}, {"idempotency_key": None},
                         {"data_exame": "lixo"}, {"data_exame": "2026-02-31"},
                         {"agendamento_id": 99}, {"atendimento_id": 99}):
            with self.subTest(override=override), self.assertRaises(HTTPException) as caught:
                self.upload(**override)
            self.assertEqual(caught.exception.status_code, 422)
        self.assertEqual(self.db.query(Laudo).count(), 0)
        self.assertEqual(self.db.query(OrdemServico).count(), 0)
        self.store_mock.assert_not_called()

    def test_inativos_e_preco_zero_nao_geram_os(self):
        for model in (Paciente, Clinica, Servico):
            row = self.db.query(model).one()
            row.ativo = False
            self.db.commit()
            with self.assertRaises(HTTPException) as caught:
                self.upload()
            self.assertEqual(caught.exception.status_code, 422)
            row.ativo = True
            self.db.commit()
        self.db.query(PrecoServicoClinica).one().preco_comercial = 0
        self.db.commit()
        with self.assertRaises(HTTPException) as caught:
            self.upload()
        self.assertEqual(caught.exception.status_code, 422)
        self.store_mock.assert_not_called()

    def test_permissao_de_laudos_nao_autoriza_os_ou_preview(self):
        user = SimpleNamespace(id=8, nome="Somente Laudos", tem_papel=lambda _: False)
        with patch.object(service, "_user_has_matrix_permission", return_value=False):
            with self.assertRaises(HTTPException) as caught:
                self.upload(current_user=user)
            self.assertEqual(caught.exception.status_code, 403)
            with self.assertRaises(HTTPException) as caught:
                laudos.preview_ordem_servico_eletrocardiograma(1, 1, "comercial", self.db, user)
            self.assertEqual(caught.exception.status_code, 403)
            response = self.upload(current_user=user, gerar_ordem_servico=False)
            self.assertIsNone(response["ordem_servico"])

    def test_detalhe_oculta_valor_de_usuario_sem_acesso_financeiro(self):
        response = self.upload()
        user = SimpleNamespace(id=8, tem_papel=lambda _: False)
        with patch.object(service, "_user_has_matrix_permission", return_value=False):
            detail = laudos.obter_laudo(response["id"], self.db, user)
        self.assertIsNone(detail["ordem_servico"])

    def test_falha_de_auditoria_reverte_laudo_os_e_arquivo(self):
        def fail_audit(_mapper, _connection, _target):
            raise RuntimeError("auditoria indisponivel")
        event.listen(AuditoriaEvento, "before_insert", fail_audit)
        try:
            with self.assertRaisesRegex(RuntimeError, "auditoria indisponivel"):
                self.upload()
        finally:
            event.remove(AuditoriaEvento, "before_insert", fail_audit)
        self.assertEqual(self.db.query(Laudo).count(), 0)
        self.assertEqual(self.db.query(OrdemServico).count(), 0)
        self.assertEqual(self.db.query(AnexoAtendimento).count(), 0)
        self.assertEqual(list(Path(self.tmp.name).glob("*.pdf")), [])

    def test_falha_de_leitura_pos_commit_preserva_pdf_e_retry(self):
        with patch.object(self.db, "refresh", side_effect=RuntimeError("leitura indisponivel")):
            with self.assertRaisesRegex(RuntimeError, "leitura indisponivel"):
                self.upload()
        self.assertEqual(self.db.query(OrdemServico).count(), 1)
        self.assertEqual(len(list(Path(self.tmp.name).glob("*.pdf"))), 1)
        self.assertEqual(self.upload()["ordem_servico"]["valor_final"], 75.5)

    def test_uploads_concorrentes_com_mesma_chave_criam_uma_cobranca(self):
        barrier = threading.Barrier(2)
        def concurrent_store(*args):
            barrier.wait(timeout=5)
            return self._store(*args)
        self.store_mock.side_effect = concurrent_store
        self.db.close()
        def run():
            with self.session() as db:
                return self.upload(db=db)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: run(), range(2)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(self.db.query(OrdemServico).count(), 1)
        self.assertEqual(self.db.query(Laudo).count(), 1)
        self.assertEqual(self.db.query(AuditoriaEvento).count(), 1)
        self.assertEqual(len(list(Path(self.tmp.name).glob("*.pdf"))), 1)

    def test_os_ativa_bloqueia_exclusao_e_troca_identidade_do_laudo(self):
        response = self.upload()
        for changes in ({"paciente_id": 2}, {"clinic_id": 2}, {"data_exame": "2026-10-04"}, {"agendamento_id": 2}, {"tipo": "ecocardiograma"}):
            with self.subTest(changes=changes), self.assertRaises(HTTPException) as caught:
                laudos.atualizar_laudo(response["id"], changes, self.db, self.user)
            self.assertEqual(caught.exception.status_code, 409)
        with self.assertRaises(HTTPException) as caught:
            laudos.deletar_laudo(response["id"], self.request(), self.db, self.user)
        self.assertEqual(caught.exception.status_code, 409)

    def test_substituir_pdf_mantem_os_e_preco_originais(self):
        response = self.upload()
        ordem = self.db.query(OrdemServico).one()
        expected = service.resumo_ordem(ordem)
        replacement = UploadFile(io.BytesIO(PDF + b"revisao"), filename="revisado.pdf", headers=Headers({"content-type": "application/pdf"}))
        with patch.object(laudos, "registrar_auditoria", return_value=None):
            asyncio.run(laudos.substituir_pdf_eletrocardiograma(
                response["id"], self.request(), replacement, self.db, self.user,
            ))
        self.db.expire_all()
        self.assertEqual(service.resumo_ordem(self.db.query(OrdemServico).one()), expected)
        self.assertEqual(self.db.query(AuditoriaEvento).count(), 1)
        self.assertEqual(self.db.query(AnexoAtendimento).one().nome_original, "revisado.pdf")

    def test_os_paga_exige_desfazer_recebimento_antes_de_cancelar(self):
        self.upload()
        ordem = self.db.query(OrdemServico).one()
        ordem.status = "Pago"
        self.db.commit()
        with self.assertRaises(HTTPException) as caught:
            ordens_servico.atualizar_ordem(ordem.id, ordens_servico.OrdemServicoUpdate(status="Cancelado"), self.request(), self.db, self.user)
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(ordem.status, "Pago")

    def test_os_preserva_origem_e_idempotencia_apos_cancelar(self):
        response = self.upload()
        ordem = self.db.query(OrdemServico).one()
        for changes in ({"paciente_id": 2}, {"clinica_id": 2}, {"data_atendimento": datetime(2026, 10, 4)}):
            with self.subTest(changes=changes), self.assertRaises(HTTPException) as caught:
                ordens_servico.atualizar_ordem(ordem.id, ordens_servico.OrdemServicoUpdate(**changes), self.request(), self.db, self.user)
            self.assertEqual(caught.exception.status_code, 409)
        ordem.status = "Cancelado"
        self.db.commit()
        with self.assertRaises(HTTPException) as caught:
            ordens_servico.deletar_ordem(ordem.id, self.request(), self.db, self.user)
        self.assertEqual(caught.exception.status_code, 409)
        with self.assertRaises(HTTPException) as caught:
            ordens_servico.atualizar_ordem(ordem.id, ordens_servico.OrdemServicoUpdate(status="Pendente"), self.request(), self.db, self.user)
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(self.upload()["ordem_servico"]["status"], "Cancelado")
        laudos.deletar_laudo(response["id"], self.request(), self.db, self.user)
        with self.assertRaises(HTTPException) as caught:
            self.upload()
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(self.db.query(OrdemServico).count(), 1)


if __name__ == "__main__":
    unittest.main()

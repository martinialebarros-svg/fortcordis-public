import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "tutor-panorama-georef-secret-key-1234567890")

from app.api.v1.endpoints import agenda, tutores
from app.models.clinica import Clinica
from app.models.paciente import Paciente
from app.models.tutor import Tutor


class TutorPanoramaGeorefTest(unittest.TestCase):
    def _build_session(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "tutor-panorama-georef.db"
        engine = create_engine(f"sqlite:///{db_path}")
        Tutor.__table__.create(engine, checkfirst=True)
        Paciente.__table__.create(engine, checkfirst=True)
        Clinica.__table__.create(engine, checkfirst=True)
        session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
        return tmpdir, session, engine

    def test_panorama_tutor_retorna_pets_e_status_georreferenciamento(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            tutor = Tutor(
                nome="Maria Silva",
                telefone="85999990000",
                endereco="Rua das Flores",
                numero="123",
                cidade="Fortaleza",
                estado="CE",
                latitude=-3.7319,
                longitude=-38.5267,
                ativo=1,
            )
            db.add(tutor)
            db.commit()
            db.refresh(tutor)

            db.add_all(
                [
                    Paciente(nome="Luna", tutor_id=tutor.id, especie="Canina", raca="SRD", ativo=1),
                    Paciente(nome="Nina", tutor_id=tutor.id, especie="Felina", raca="Siames", ativo=1),
                ]
            )
            db.commit()

            response = tutores.obter_panorama_tutor(
                tutor.id,
                db=db,
                current_user=SimpleNamespace(id=1),
            )

            self.assertEqual(response["tutor"]["id"], tutor.id)
            self.assertTrue(response["resumo"]["georreferenciado"])
            self.assertEqual(response["resumo"]["total_pets"], 2)
            self.assertEqual([item["nome"] for item in response["pets"]], ["Luna", "Nina"])
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_geocode_endereco_tutor_retorna_payload_google(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            with patch.object(
                tutores,
                "geocodificar_endereco_google",
                return_value=SimpleNamespace(
                    latitude=-3.7319,
                    longitude=-38.5267,
                    place_id="place-123",
                    endereco_normalizado="Rua das Flores, 123 - Fortaleza - CE, Brasil",
                    bairro="Centro",
                    cidade="Fortaleza",
                    estado="CE",
                    cep="60000000",
                ),
            ):
                response = tutores.geocode_endereco_tutor(
                    payload=tutores.GeocodeEnderecoPayload(
                        endereco="Rua das Flores",
                        numero="123",
                        cidade="Fortaleza",
                        estado="CE",
                        cep="60000-000",
                    ),
                    db=db,
                    current_user=SimpleNamespace(id=1),
                )

            self.assertTrue(response["ok"])
            self.assertEqual(response["item"]["place_id"], "place-123")
            self.assertEqual(response["item"]["bairro"], "Centro")
            self.assertEqual(response["item"]["latitude"], -3.7319)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_listar_tutores_expoe_campos_endereco_para_fluxo_domiciliar(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            tutor = Tutor(
                nome="Carlos Mendes",
                telefone="85988887777",
                endereco="Av. Santos Dumont",
                numero="456",
                bairro="Aldeota",
                cidade="Fortaleza",
                estado="CE",
                cep="60150-160",
                latitude=-3.7319,
                longitude=-38.4966,
                endereco_normalizado="Av. Santos Dumont, 456 - Aldeota, Fortaleza - CE",
                ativo=1,
            )
            db.add(tutor)
            db.commit()

            response = tutores.listar_tutores(limit=50, db=db, current_user=SimpleNamespace(id=1))

            self.assertEqual(response["total"], 1)
            self.assertEqual(response["items"][0]["id"], tutor.id)
            self.assertEqual(response["items"][0]["endereco"], "Av. Santos Dumont")
            self.assertEqual(response["items"][0]["numero"], "456")
            self.assertEqual(response["items"][0]["bairro"], "Aldeota")
            self.assertEqual(response["items"][0]["estado"], "CE")
            self.assertEqual(response["items"][0]["endereco_normalizado"], tutor.endereco_normalizado)
            self.assertTrue(response["items"][0]["georreferenciado"])
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_listar_tutores_nao_marca_coordenadas_zero_como_georreferenciadas(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            tutor = Tutor(
                nome="Tutor invalido",
                telefone="85988887777",
                latitude=0.0,
                longitude=0.0,
                ativo=1,
            )
            db.add(tutor)
            db.commit()

            response = tutores.listar_tutores(limit=50, db=db, current_user=SimpleNamespace(id=1))

            self.assertEqual(response["total"], 1)
            self.assertIsNone(response["items"][0]["latitude"])
            self.assertIsNone(response["items"][0]["longitude"])
            self.assertFalse(response["items"][0]["georreferenciado"])
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_busca_tutor_acontece_antes_da_paginacao_e_aceita_nome_ou_telefone(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            db.add_all(
                [
                    Tutor(
                        nome=f"Tutor comum {indice:03d}",
                        nome_key=f"tutor comum {indice:03d}",
                        ativo=1,
                    )
                    for indice in range(60)
                ]
            )
            db.add_all(
                [
                    Tutor(
                        nome="Jéfferson remoto",
                        nome_key="jefferson remoto",
                        telefone="(85) 99806-9930",
                        ativo=1,
                    ),
                    Tutor(nome="JEFERSON", nome_key="jeferson", ativo=1),
                    Tutor(
                        nome="Jefferson da Silva",
                        nome_key="jefferson da silva",
                        ativo=1,
                    ),
                ]
            )
            db.commit()
            tutor_remoto = (
                db.query(Tutor)
                .filter(Tutor.nome_key == "jefferson remoto")
                .one()
            )
            db.add(
                Paciente(
                    nome="Billy remoto",
                    nome_key="billy remoto",
                    tutor_id=tutor_remoto.id,
                    ativo=1,
                )
            )
            db.commit()

            por_nome = tutores.listar_tutores(
                limit=10,
                busca="Jeferson",
                db=db,
                current_user=SimpleNamespace(id=1),
            )
            por_telefone = tutores.listar_tutores(
                limit=10,
                busca="99806",
                db=db,
                current_user=SimpleNamespace(id=1),
            )
            por_pet = tutores.listar_tutores(
                limit=10,
                busca="Billy remoto",
                db=db,
                current_user=SimpleNamespace(id=1),
            )

            self.assertEqual(por_nome["total"], 3)
            remoto_por_nome = next(
                item for item in por_nome["items"]
                if item["nome"] == "Jéfferson remoto"
            )
            self.assertEqual(remoto_por_nome["total_pets"], 1)
            self.assertEqual(
                remoto_por_nome["pets"],
                [{"id": por_pet["items"][0]["pets"][0]["id"], "nome": "Billy remoto"}],
            )
            self.assertEqual(por_telefone["total"], 1)
            self.assertEqual(por_telefone["items"][0]["nome"], "Jéfferson remoto")
            self.assertEqual(por_pet["total"], 1)
            self.assertEqual(por_pet["items"][0]["nome"], "Jéfferson remoto")
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_sugestao_horario_exige_clinica_georreferenciada(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            clinica = Clinica(nome="Clinica sem geo", cidade="Fortaleza", estado="CE", ativo=True)
            db.add(clinica)
            db.commit()
            db.refresh(clinica)

            with self.assertRaises(HTTPException) as ctx:
                agenda.sugerir_horarios_agenda(
                    payload=agenda.SugestaoHorarioPayload(
                        data="2030-01-15",
                        clinica_id=clinica.id,
                    ),
                    db=db,
                    current_user=SimpleNamespace(id=1),
                )

            self.assertEqual(ctx.exception.status_code, 422)
            self.assertIn("georreferenciado", str(ctx.exception.detail).lower())
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()

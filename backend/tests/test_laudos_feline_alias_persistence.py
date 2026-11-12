"""Real HTTP and disposable SQLite round trips for historical feline ratios.

The frontend owns derivation. These checks ensure a correct client payload is
stored and reopened verbatim; they do not invent or repair clinical values in
the API. The same harness can replay captured payloads from both report pages.
"""

import copy
import os
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "synthetic-feline-persistence-test-secret-123456789")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.v1.endpoints import laudos, pacientes
from app.db.database import Base, get_db
from app.models.laudo import Laudo
from app.models.paciente import Paciente
from app.utils.ecocardiograma_medidas import extrair_medidas_ecocardiograma_da_descricao


HISTORICAL_RATIOS = {
    "E_A": "1.13",
    "E_TRIV": "2.66",
    "E_E_linha": "6.95",
    "doppler_tecidual_relacao": "2.60",
}
ORIGIN_MEASUREMENTS = {
    "Onda_E": "1.08",
    "Onda_A": "0.95",
    "TRIV": "40",
    "e_doppler": "0.16",
    "a_doppler": "0.06",
}
# Explicit operator-removal fixture, matching the clinical frontend groups.
# This list is not an API cleanup rule: the backend stores the submitted report.
EXPLICIT_FUSION_REMOVAL_KEYS = {
    "transmitral": ("Onda_E", "Onda_A", "E_A", "TD", "E_TRIV", "E_E_linha"),
    "tissue": ("e_doppler", "a_doppler", "doppler_tecidual_relacao", "E_E_linha"),
}


def synthetic_measurements(waves: str) -> dict[str, str]:
    measurements = {**ORIGIN_MEASUREMENTS, **HISTORICAL_RATIOS}
    if waves == "fundidas":
        measurements.update(Diastolica_ondas="fundidas", TDI_ondas="fundidas")
    return measurements


def synthetic_description(measurements: dict[str, str]) -> str:
    return "## Medidas Ecocardiograficas\n" + "".join(
        f"- {key}: {value}\n" for key, value in measurements.items()
    ) + "\n## Avaliacao Qualitativa\n"


@contextmanager
def isolated_laudo_http(species: str):
    """Use the production routers with only database/auth dependencies replaced.

    Every request creates and closes its own Session. No endpoint, serializer,
    patient update, commit, or extraction function is mocked.
    """
    with tempfile.TemporaryDirectory(prefix="feline-alias-http-") as directory:
        engine = create_engine(
            f"sqlite:///{directory}/test.db",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(engine)
        sessions = sessionmaker(bind=engine, autoflush=False)
        user = SimpleNamespace(id=7, nome="Veterinario sintetico", email="qa@example.invalid")
        with sessions() as db:
            db.add(Paciente(id=901, nome="TESTE FELINO SINTETICO", especie=species, ativo=1))
            db.commit()

        def get_test_db():
            with sessions() as db:
                yield db

        app = FastAPI()
        app.include_router(laudos.router)
        app.include_router(pacientes.router, prefix="/pacientes")
        app.dependency_overrides[get_db] = get_test_db
        app.dependency_overrides[laudos.get_current_user] = lambda: user
        try:
            with TestClient(app) as client:
                yield client, sessions
        finally:
            engine.dispose()


def replay_page_save(case: dict) -> dict:
    """Replay a captured new/edit page payload and reopen in a fresh session."""
    species = case["species"]
    mode = case["mode"]
    payload = copy.deepcopy(case["payload"])
    with isolated_laudo_http(species) as (client, sessions):
        if mode == "novo":
            saved = client.post("/laudos", json=payload)
            assert saved.status_code == 201, saved.text
            laudo_id = saved.json()["id"]
        else:
            # Start from a persisted historical report, not from a mutated object
            # left in the same ORM Session as the request under test.
            with sessions() as db:
                original = Laudo(
                    paciente_id=901,
                    veterinario_id=7,
                    tipo="ecocardiograma",
                    titulo="TESTE FELINO SINTETICO",
                    descricao=case.get("initial_description") or synthetic_description(
                        synthetic_measurements(case["scenario"])
                    ),
                    diagnostico="TESTE SINTETICO SEM VALIDADE CLINICA",
                    status="Rascunho",
                )
                db.add(original)
                db.commit()
                laudo_id = original.id
            if case.get("paciente_payload"):
                patient_saved = client.put("/pacientes/901", json=case["paciente_payload"])
                assert patient_saved.status_code == 200, patient_saved.text
            saved = client.put(f"/laudos/{laudo_id}", json=payload)
            assert saved.status_code == 200, saved.text

        reopened = client.get(f"/laudos/{laudo_id}")
        assert reopened.status_code == 200, reopened.text
        response = reopened.json()
        if case.get("captured_description") is not None:
            assert response["medidas"] == extrair_medidas_ecocardiograma_da_descricao(
                case["captured_description"]
            )
            if mode == "editar":
                assert response["descricao"] == case["captured_description"]
        with sessions() as db:
            record = db.get(Laudo, laudo_id)
            patient = db.get(Paciente, record.paciente_id)
            database_measurements = extrair_medidas_ecocardiograma_da_descricao(record.descricao)
            assert response["medidas"] == database_measurements
            assert response["paciente"]["especie"] == patient.especie
            assert patient.especie == species
            # Saving the technical test must not create a portal exam or send.
            assert response["whatsapp_envios"] == {}
            assert not response["portal_clinica_liberado"]
            ratios = {key: database_measurements.get(key) for key in HISTORICAL_RATIOS}
        return {
            "species": species,
            "scenario": case["scenario"],
            "mode": mode,
            "http_status": saved.status_code,
            "reopened_species": response["paciente"]["especie"],
            "ratios": ratios,
            "medidas": database_measurements,
            "descricao": response["descricao"],
            "separate_database_sessions": True,
        }


class LaudosFelineAliasPersistenceTest(unittest.TestCase):
    def test_explicit_removal_survives_real_post_put_and_fresh_get_without_resurrecting_values(self):
        for species in ("Gato", "Cat"):
            for mode in ("novo", "editar"):
                for group, removed_keys in EXPLICIT_FUSION_REMOVAL_KEYS.items():
                    with self.subTest(species=species, mode=mode, group=group):
                        recorded = {
                            **ORIGIN_MEASUREMENTS,
                            **HISTORICAL_RATIOS,
                            "TD": "51",
                            "DIVEd": "17.06",
                            "VE_tecnica_relatorio": "modo_m",
                            "Diastolica_metodo": "felino_adulto_nao_sedado_pw_apical_clique_aortico",
                            "Diastolica_ondas": "fundidas" if group == "transmitral" else "separadas",
                            "TDI_metodo": "felino_pw_anel_lateral",
                            "TDI_ondas": "separadas" if group == "transmitral" else "fundidas",
                        }
                        before = copy.deepcopy(recorded)
                        explicitly_corrected = {
                            key: value for key, value in recorded.items() if key not in removed_keys
                        }
                        description = synthetic_description(explicitly_corrected)
                        patient = {"id": 901, "nome": "TESTE FELINO SINTETICO", "especie": species}
                        payload = {
                            "paciente": patient,
                            "medidas": explicitly_corrected,
                            "qualitativa": {},
                            "conteudo": {"conclusao": "TESTE SINTETICO SEM VALIDADE CLINICA"},
                            "tipo_laudo": "ecocardiograma",
                            "status": "Rascunho",
                        }
                        if mode == "editar":
                            payload = {"descricao": description, "tipo_laudo": "ecocardiograma", "status": "Rascunho"}
                        result = replay_page_save({
                            "species": species,
                            "scenario": "fundidas",
                            "mode": mode,
                            "payload": payload,
                            "paciente_payload": patient,
                            "initial_description": synthetic_description(recorded),
                            "captured_description": description,
                        })
                        self.assertEqual(result["medidas"], explicitly_corrected)
                        for key in removed_keys:
                            self.assertNotIn(key, result["medidas"])
                            self.assertNotIn(f"- {key}:", result["descricao"])
                        for key in ("TRIV", "DIVEd", "VE_tecnica_relatorio", "Diastolica_metodo", "Diastolica_ondas", "TDI_metodo", "TDI_ondas"):
                            self.assertEqual(result["medidas"][key], recorded[key])
                        independent = (
                            ("e_doppler", "a_doppler", "doppler_tecidual_relacao")
                            if group == "transmitral" else ("Onda_E", "Onda_A", "E_A", "TD", "E_TRIV")
                        )
                        for key in independent:
                            self.assertEqual(result["medidas"][key], recorded[key])
                        self.assertEqual(recorded, before)

    def test_historical_fused_and_unconfirmed_ratios_survive_post_put_get(self):
        # Frontend regression tests cover actual page effects and derivation.
        # Here the persisted contract is checked independently through HTTP.
        for species in ("Felina", "Felino", "Feline", "Gato", "Gatos", "Cat", "Cats"):
            for waves in ("fundidas", "desconhecidas"):
                for mode in ("novo", "editar"):
                    with self.subTest(species=species, waves=waves, mode=mode):
                        measurements = synthetic_measurements(waves)
                        payload = {
                            "paciente": {
                                "id": 901,
                                "nome": "TESTE FELINO SINTETICO",
                                "especie": species,
                            },
                            "medidas": measurements,
                            "qualitativa": {},
                            "conteudo": {"conclusao": "TESTE SINTETICO SEM VALIDADE CLINICA"},
                            "tipo_laudo": "ecocardiograma",
                            "status": "Rascunho",
                        }
                        if mode == "editar":
                            payload = {
                                "descricao": synthetic_description(measurements),
                                "tipo_laudo": "ecocardiograma",
                                "status": "Rascunho",
                            }
                        result = replay_page_save({
                            "species": species,
                            "scenario": waves,
                            "mode": mode,
                            "payload": payload,
                        })
                        self.assertEqual(result["ratios"], HISTORICAL_RATIOS)
                        for key, value in ORIGIN_MEASUREMENTS.items():
                            self.assertEqual(result["medidas"][key], value)
                        if waves == "fundidas":
                            self.assertEqual(result["medidas"]["Diastolica_ondas"], waves)
                            self.assertEqual(result["medidas"]["TDI_ondas"], waves)
                        else:
                            self.assertNotIn("Diastolica_ondas", result["medidas"])
                            self.assertNotIn("TDI_ondas", result["medidas"])


if __name__ == "__main__":
    unittest.main()

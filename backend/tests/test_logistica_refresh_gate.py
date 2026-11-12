import os
import sys
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "logistica-refresh-gate-test-secret-key-1234567890")

from app.models.clinica import Clinica
from app.models.clinica_deslocamento import ClinicaDeslocamento
from app.services import logistica_service


class LogisticaRefreshGateTest(unittest.TestCase):
    def _build_clinicas_e_row(self) -> tuple[Clinica, Clinica, ClinicaDeslocamento]:
        origem = Clinica(id=1, nome="Origem", latitude=-3.7200, longitude=-38.5200)
        destino = Clinica(id=2, nome="Destino", latitude=-3.8100, longitude=-38.6100)
        row = ClinicaDeslocamento(
            origem_clinica_id=1,
            destino_clinica_id=2,
            perfil="comercial",
            distancia_km=Decimal("12.30"),
            duracao_min=24,
            fonte="heuristica_haversine",
            manual_override=False,
            updated_at=datetime.utcnow(),
        )
        return origem, destino, row

    def test_heuristica_permanece_atual_quando_gate_esta_desligado(self) -> None:
        origem, destino, row = self._build_clinicas_e_row()

        with patch.object(logistica_service.settings, "GOOGLE_MAPS_API_KEY", "fake-key"), patch.object(
            logistica_service.settings,
            "LOGISTICA_FORCE_REFRESH_HEURISTICA_COM_API_KEY",
            False,
        ):
            atual = logistica_service._deslocamento_esta_atual(row, origem=origem, destino=destino)

        self.assertTrue(atual)

    def test_heuristica_fica_stale_quando_gate_esta_ligado(self) -> None:
        origem, destino, row = self._build_clinicas_e_row()

        with patch.object(logistica_service.settings, "GOOGLE_MAPS_API_KEY", "fake-key"), patch.object(
            logistica_service.settings,
            "LOGISTICA_FORCE_REFRESH_HEURISTICA_COM_API_KEY",
            True,
        ):
            atual = logistica_service._deslocamento_esta_atual(row, origem=origem, destino=destino)

        self.assertFalse(atual)


if __name__ == "__main__":
    unittest.main()

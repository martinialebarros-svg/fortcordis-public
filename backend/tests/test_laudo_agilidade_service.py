import os
import sys
import unittest
from datetime import datetime
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "laudo-agilidade-service-test-secret-key-1234567890")

from app.services.laudo_agilidade_service import horas_uteis_entre

FERIADOS = [{"data": "2026-08-20", "descricao": "Feriado local", "tipo": "local"}]


class LaudoAgilidadeServiceTest(unittest.TestCase):
    def test_intervalo_todo_num_dia_util(self) -> None:
        # Segunda-feira 2026-08-17: 10h -> 16h = 6h.
        inicio = datetime(2026, 8, 17, 10, 0)
        fim = datetime(2026, 8, 17, 16, 0)
        self.assertAlmostEqual(horas_uteis_entre(inicio, fim, []), 6.0)

    def test_fim_menor_ou_igual_inicio_retorna_zero(self) -> None:
        marco = datetime(2026, 8, 17, 10, 0)
        self.assertEqual(horas_uteis_entre(marco, marco, []), 0.0)
        self.assertEqual(horas_uteis_entre(marco, marco.replace(hour=9), []), 0.0)

    def test_intervalo_cruzando_fim_de_semana(self) -> None:
        # Sexta 2026-08-14, 14h -> Segunda 2026-08-17, 10h.
        # Sexta: 14h->24h = 10h. Sabado/domingo: 0h. Segunda: 0h->10h = 10h.
        # Total = 20h uteis (48h corridas reais, mas so 20h contam).
        inicio = datetime(2026, 8, 14, 14, 0)
        fim = datetime(2026, 8, 17, 10, 0)
        self.assertAlmostEqual(horas_uteis_entre(inicio, fim, []), 20.0)

    def test_intervalo_cruzando_feriado_cadastrado(self) -> None:
        # Quinta 2026-08-20 e feriado (ver FERIADOS). Terca 2026-08-18, 8h ->
        # Sexta 2026-08-21, 8h.
        # Terca: 8h->24h=16h. Quarta: 24h. Quinta (feriado): 0h. Sexta: 8h.
        # Total = 16+24+0+8 = 48h.
        inicio = datetime(2026, 8, 18, 8, 0)
        fim = datetime(2026, 8, 21, 8, 0)
        self.assertAlmostEqual(horas_uteis_entre(inicio, fim, FERIADOS), 48.0)
        # Sem o feriado cadastrado, o mesmo intervalo teria 72h uteis.
        self.assertAlmostEqual(horas_uteis_entre(inicio, fim, []), 72.0)

    def test_realizado_sexta_a_noite_so_fica_atrasado_apos_util_suficiente(self) -> None:
        # Sexta 2026-08-14, 20h - 48h uteis (RF-6/CA-6) so se completam
        # depois de consumir sexta (4h), sabado/domingo (0h), segunda (24h)
        # e parte de terca (20h) = 4+24+20 = 48h em 2026-08-18 as 20h.
        inicio = datetime(2026, 8, 14, 20, 0)
        antes_do_prazo = datetime(2026, 8, 18, 19, 0)
        no_prazo_exato = datetime(2026, 8, 18, 20, 0)
        self.assertLess(horas_uteis_entre(inicio, antes_do_prazo, []), 48.0)
        self.assertAlmostEqual(horas_uteis_entre(inicio, no_prazo_exato, []), 48.0)


if __name__ == "__main__":
    unittest.main()

"""Real HTTP/PDF regressions: a preview never changes an issued document."""
from copy import deepcopy
from datetime import datetime, timedelta
from io import BytesIO
import unittest
from unittest.mock import patch
from uuid import uuid4

from PIL import Image, ImageDraw
from pypdf import PdfReader
from sqlalchemy import event, select

from tests import test_laudo_editor_drafts as _draft_tests
from app.api.v1.endpoints import laudos
from app.db.database import Base
from app.models.clinica import Clinica
from app.models.configuracao import Configuracao, ConfiguracaoUsuario
from app.models.imagem_laudo import ImagemLaudo, ImagemTemporaria
from app.models.laudo import Laudo
from app.models.paciente import Paciente
from app.models.papel_permissao import PapelPermissao
from app.models.referencia_eco import ReferenciaEco
from app.models.user import User
from app.services.laudo_pdf_service import compute_laudo_pdf_cache_key, render_laudo_pdf
from app.utils.echo_pulmonary_probability import make_pulmonary_review_stamp


def png(color="teal"):
    stream = BytesIO()
    Image.new("RGB", (120, 80), color).save(stream, format="PNG")
    return stream.getvalue()


def logo_png():
    # Synthetic branding only: transparent right-side padding keeps the mark
    # inside the existing official logo column instead of covering its title.
    canvas=Image.new("RGBA",(400,160),(0,0,0,0))
    draw=ImageDraw.Draw(canvas)
    draw.rectangle((8,30,96,126),fill="teal")
    draw.text((30,65),"QA",fill="white")
    stream=BytesIO(); canvas.save(stream,format="PNG")
    return stream.getvalue()


def text(content, *, remove_preview=False):
    pages = PdfReader(BytesIO(content)).pages
    lines = "\n".join(page.extract_text() or "" for page in pages).splitlines()
    return "\n".join(line for line in lines if not remove_preview or line != "PRÉVIA - NÃO EMITIDO")


class EchoPdfPreviewHTTPTest(unittest.TestCase):
    def setUp(self):
        self.harness = _draft_tests.EditorDraftHTTPTest()
        self.harness.setUp()
        self.__dict__.update({key: value for key, value in self.harness.__dict__.items() if not key.startswith("_")})
        self.app.include_router(laudos.router, prefix="/api/v1")
        with self.sessions() as db:
            db.add_all([PapelPermissao(papel_id=1, modulo=module, visualizar=1, editar=1, excluir=0)
                        for module in ("pacientes", "tutores")])
            db.add(Clinica(id=901, nome="CLINICA SINTETICA", ativo=1))
            db.add(Configuracao(id=1, mostrar_logomarca=True, logomarca_dados=logo_png(),
                                texto_rodape_laudo="RODAPE SINTETICO", mostrar_assinatura=True,
                                assinatura_dados=png("navy")))
            db.add(ConfiguracaoUsuario(user_id=1, crmv="TESTE/ZZ"))
            db.add_all([
                ImagemLaudo(id=71, laudo_id=901, nome_arquivo="first.png", conteudo=png("red"),
                            ordem=0, descricao="Original A", incluir_no_pdf=True, ativo=1),
                ImagemLaudo(id=72, laudo_id=901, nome_arquivo="second.png", conteudo=png("blue"),
                            ordem=1, descricao="Original B", incluir_no_pdf=True, ativo=1),
                Laudo(id=902, paciente_id=901, veterinario_id=1, tipo="ecocardiograma", titulo="OUTRO SINTETICO"),
                ImagemLaudo(id=73, laudo_id=902, nome_arquivo="foreign.png", conteudo=png(), ordem=0, ativo=1),
            ])
            db.commit()
        self.preview_url = self.url + "/preview"

    def tearDown(self):
        self.harness.tearDown()

    def headers(self, token="editor"):
        return _draft_tests.EditorDraftHTTPTest.headers(token)

    def state(self):
        with self.engine.connect() as connection:
            return {table.name: [tuple(row) for row in connection.execute(select(table))]
                    for table in Base.metadata.sorted_tables}

    def source_revision(self):
        response = self.client.get("/api/v1/laudos/901", headers=self.headers())
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["editor_revision"]

    def save(self, *, existing=False, images=None, session="preview-synthetic-session"):
        snapshot = {"schema_version": 1, "editor": "existing-echo" if existing else "new-echo",
                    "paciente": {}, "medidas": {}, "sessionId": session, "imagens": images or []}
        if existing:
            snapshot["source"] = {"laudo_id": 901, "editor_revision": self.source_revision()}
        body = {"expected_revision": 0, "request_id": str(uuid4()),
                "context_key": "edit:laudo:901" if existing else "new:blank", "snapshot": snapshot}
        response = self.client.put(self.url, headers=self.headers(), json=body)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def new_body(self):
        return {"expected_revision": 1, "payload_laudo": {
            "paciente": {"nome": "TESTE PREVIA LOCAL", "tutor": "TUTOR SINTETICO", "especie": "Canina",
                         "raca": "SRD", "sexo": "Macho", "peso": "2.5", "idade": "5a", "data_exame": "2026-10-01"},
            "medidas": {"DIVEd": "17.25", "DIVES": "9.5", "unidade_confirmada_DIVEd": "mm",
                        "VE_tecnica_relatorio": "modo_m", "AE_Ao": "1.41"},
            "qualitativa": {"vasos": "Texto manual sintético preservado."},
            "conteudo": {"conclusao": "Conclusão sintética de teste.", "observacoes": "Observação privada."},
            "tipo_laudo": "ecocardiograma", "status": "Finalizado", "clinica": {"id": 901},
            "veterinario": {"nome": "Solicitante SINTETICO"}, "ecocardiograma_cabecalho": {"fc": "130"},
            "pressao_arterial": {"pas_1": 120, "pas_2": 125, "pas_3": 130},
        }, "imagens": {"persistidas": [], "removidas_ids": [], "temp_config": [],
                        "temp_session_id": "preview-synthetic-session"}}

    def existing_body(self):
        return {"expected_revision": 1, "payload_laudo": {
            "descricao": laudos._montar_descricao_ecocardiograma({"DIVEd": "19.5", "VE_tecnica_relatorio": "modo_m"},
                                                                 {"vasos": "Manual da edição sintética."}),
            "diagnostico": "Conclusão manual da edição.", "status": "Finalizado", "tipo_laudo": "ecocardiograma",
            "data_exame": "2026-10-01", "clinic_id": 901,
            "ecocardiograma_cabecalho": {"fc": "160", "ritmo": "Sinusal"},
        }, "imagens": {"persistidas": [{"id": 72, "ordem": 0, "descricao": "Legenda B revisada"}],
                        "removidas_ids": [71], "temp_config": [], "temp_session_id": "preview-synthetic-session"}}

    def post(self, body, token="editor", headers=None):
        return self.client.post(self.preview_url, json=body, headers=self.headers(token) if headers is None else headers)

    def assert_pdf(self, response):
        self.assertEqual(response.status_code, 200, response.text[:300])
        self.assertEqual(response.headers["content-type"], "application/pdf")
        self.assertEqual(response.headers["cache-control"], "private, no-store")
        self.assertTrue(response.headers["content-disposition"].startswith("inline;"))
        self.assertRegex(response.headers["x-echo-preview-snapshot"], r"^[a-f0-9]{64}$")
        self.assertTrue(response.content.startswith(b"%PDF-"))
        for page in PdfReader(BytesIO(response.content)).pages:
            self.assertIn("PRÉVIA - NÃO EMITIDO", page.extract_text())

    def assert_preview_matches_official(self, preview, laudo_id):
        with self.sessions() as db:
            official = render_laudo_pdf(db, laudo_id, db.get(User, 1)).content
        self.assertEqual(text(preview, remove_preview=True), text(official))
        self.assertEqual(len(PdfReader(BytesIO(preview)).pages), len(PdfReader(BytesIO(official)).pages))
        return official

    def test_new_real_pdf_and_retry_have_zero_database_or_clinical_side_effects_and_match_emission(self):
        self.save()
        body = self.new_body()
        before = self.state()
        statements = []
        def record(_connection, _cursor, statement, _parameters, _context, _executemany):
            statements.append(statement.lstrip().upper())
        event.listen(self.engine, "before_cursor_execute", record)
        try:
            with patch.object(laudos, "_resolver_ou_criar_paciente", side_effect=AssertionError("clinical write")), \
                 patch.object(laudos, "_atualizar_laudo_transacional", side_effect=AssertionError("clinical update")), \
                 patch.object(laudos, "_persistir_pdf_laudo_para_portal", side_effect=AssertionError("portal write")), \
                 patch.object(laudos, "enqueue_laudo_pdf_job", side_effect=AssertionError("PDF job")):
                response = self.post(body)
                self.assert_pdf(response)
                repeated = self.post(body)
                self.assert_pdf(repeated)
                self.assertEqual(response.headers["x-echo-preview-snapshot"], repeated.headers["x-echo-preview-snapshot"])
        finally:
            event.remove(self.engine, "before_cursor_execute", record)
        self.assertFalse(any(statement.startswith(("INSERT", "UPDATE", "DELETE")) for statement in statements))
        self.assertEqual(self.state(), before)
        emitted = self.client.post("/api/v1/laudos", json=body["payload_laudo"], headers=self.headers())
        self.assertEqual(emitted.status_code, 201, emitted.text)
        self.assert_preview_matches_official(response.content, emitted.json()["id"])

    def test_existing_manual_text_demographics_images_are_projected_without_mutation_then_match_atomic_update(self):
        saved = self.save(existing=True)
        body = self.existing_body()
        body["paciente"] = {"nome": "TESTE NOME REVISADO", "idade": "12a", "peso_kg": 5.2}
        body["tutor"] = {"id": 901, "nome": "TESTE TUTOR REVISADO"}
        body["payload_laudo"]["ecocardiograma_estruturado"] = {
            "usar_no_laudo": True, "textos": {"valva_mitral": "Preset ainda não aplicado.", "conclusao": "NÃO APLICADA"}}
        body["payload_laudo"].update(aplicar_qualitativa_estruturada=False, aplicar_conclusao_estruturada=False)
        before = self.state()
        response = self.post(body)
        self.assert_pdf(response)
        self.assertEqual(self.state(), before)
        rendered = text(response.content)
        for expected in ("TESTE NOME REVISADO", "TESTE TUTOR REVISADO", "Manual da edição sintética", "Conclusão manual da edição", "Legenda B revisada"):
            self.assertIn(expected, rendered)
        self.assertNotIn("NÃO APLICADA", rendered)
        self.assertNotIn("Original A", rendered)
        update = {"expected_editor_revision": saved["snapshot"]["source"]["editor_revision"],
                  "request_id": str(uuid4()), "editor_draft_id": saved["draft_id"],
                  "expected_draft_revision": saved["revision"],
                  **{key: value for key, value in body.items() if key != "expected_revision"}}
        with patch.object(laudos, "_sincronizar_publicacao_laudo_no_portal", return_value=(None, None, None, None)):
            result = self.client.put("/api/v1/laudos/901/editor-update", json=update, headers=self.headers())
        self.assertEqual(result.status_code, 200, result.text)
        self.assert_preview_matches_official(response.content, 901)

    def test_other_report_types_use_same_declared_age_in_details_and_pdf(self):
        for kind in ("pressao_arterial", "ultrassonografia_abdominal"):
            with self.subTest(kind=kind):
                payload = self.new_body()["payload_laudo"]
                payload.update(tipo_laudo=kind, status="Rascunho")
                payload["paciente"].update(id=901, tutor_id=901, idade_informada="12 anos",
                                           idade_referencia="2026-10-01", idade_fonte="idade",
                                           data_nascimento="2026-09-30")
                result = self.client.post("/api/v1/laudos", json=payload, headers=self.headers())
                self.assertEqual(result.status_code, 201, result.text)
                report_id = result.json()["id"]
                details = self.client.get(f"/api/v1/laudos/{report_id}", headers=self.headers()).json()
                self.assertEqual(details["paciente"]["idade"], "12a (estimada)")
                with self.sessions() as db:
                    rendered = render_laudo_pdf(db, report_id, db.get(User, 1))
                self.assertIn("12a (estimada)", text(rendered.content))

    def test_new_birth_source_never_stores_derived_age_as_declared_age(self):
        from app.utils.paciente_idade import alteracoes_idade, idade_do_paciente
        payload = self.new_body()["payload_laudo"]["paciente"]
        payload.update(tutor_id=901, data_nascimento="2014", idade="11–12 anos (estimada pelo ano)",
                       idade_informada=None, idade_referencia=None, idade_fonte="nascimento")
        with self.sessions() as db:
            patient_id = laudos._resolver_ou_criar_paciente(payload, db)
            patient = db.get(Paciente, patient_id)
            self.assertIsNone(patient.idade_informada)
            self.assertNotIn("Idade:", patient.observacoes or "")
            for key, value in alteracoes_idade(patient, {"data_nascimento": None}).items():
                setattr(patient, key, value)
            self.assertEqual(idade_do_paciente(patient), "")

    def test_explicit_age_metadata_survives_preview_apply_read_and_pdf_cache(self):
        with self.sessions() as db:
            patient = db.get(Paciente, 901)
            patient.nascimento = "2026-09-30"
            patient.observacoes = "Nota clínica sintética"
            db.commit()
            old_key = compute_laudo_pdf_cache_key(db, 901, 1)
        saved = self.save(existing=True)
        body = self.existing_body()
        body["paciente"] = {"idade_informada": "12 anos", "idade_fonte": "idade",
                            "idade_referencia": "2026-10-01", "data_nascimento": "2026-09-30"}
        before = self.state()
        preview = self.post(body)
        self.assert_pdf(preview)
        self.assertIn("12a (estimada)", text(preview.content))
        self.assertEqual(self.state(), before)
        update = {"expected_editor_revision": saved["snapshot"]["source"]["editor_revision"],
                  "request_id": str(uuid4()), "editor_draft_id": saved["draft_id"],
                  "expected_draft_revision": saved["revision"],
                  **{key: value for key, value in body.items() if key != "expected_revision"}}
        with patch.object(laudos, "_sincronizar_publicacao_laudo_no_portal", return_value=(None, None, None, None)):
            applied = self.client.put("/api/v1/laudos/901/editor-update", json=update, headers=self.headers())
        self.assertEqual(applied.status_code, 200, applied.text)
        self.assert_preview_matches_official(preview.content, 901)
        patient = self.client.get("/api/v1/laudos/901", headers=self.headers()).json()["paciente"]
        self.assertEqual(patient["idade"], "12a (estimada)")
        self.assertEqual(patient["idade_fonte"], "idade")
        self.assertEqual(patient["idade_referencia"], "2026-10-01")
        self.assertEqual(patient["data_nascimento"], "2026-09-30")
        with self.sessions() as db:
            row = db.get(Paciente, 901)
            self.assertIn("Nota clínica sintética", row.observacoes)
            key = compute_laudo_pdf_cache_key(db, 901, 1)
            self.assertNotEqual(key, old_key)
            row.idade_fonte = "nascimento"
            db.commit()
            # A cadastro correction alone invalidates a previously cached download.
            self.assertNotEqual(compute_laudo_pdf_cache_key(db, 901, 1), key)

    def test_new_structured_override_and_explicit_age_match_creation_despite_existing_birthdate(self):
        self.save()
        with self.sessions() as db:
            db.get(Paciente, 901).nascimento = "2021-10-02"
            db.commit()
        body = self.new_body()
        body["payload_laudo"]["paciente"].update(id=901, tutor_id=901, idade="99a", tutor="NOME DIGITADO NÃO É VÍNCULO")
        body["payload_laudo"]["ecocardiograma_estruturado"] = {
            "usar_no_laudo": True, "textos": {"valva_mitral": "Estruturado novo aplicado.", "conclusao": "Conclusão estruturada aplicada."}}
        response = self.post(body)
        self.assert_pdf(response)
        self.assertIn("Estruturado novo aplicado", text(response.content))
        self.assertIn("Conclusão estruturada aplicada", text(response.content))
        self.assertIn("99a (estimada)", text(response.content))
        self.assertNotIn("4a 11m", text(response.content))
        self.assertNotIn("NOME DIGITADO NÃO", text(response.content))
        emitted = self.client.post("/api/v1/laudos", json=body["payload_laudo"], headers=self.headers())
        self.assertEqual(emitted.status_code, 201, emitted.text)
        self.assert_preview_matches_official(response.content, emitted.json()["id"])

    def test_auth_owner_revision_and_payload_failures_never_write(self):
        self.save()
        body = self.new_body()
        before = self.state()
        cases = [(None, None, 401), ("reader", None, 403), ("inactive", None, 403),
                 ("other", None, 404), ("editor", {"Authorization": "Bearer editor"}, 422),
                 ("editor", {**self.headers(), "X-Editor-Owner-Id": "2"}, 403)]
        for token, headers, status in cases:
            with self.subTest(token=token, headers=headers):
                result = self.post(body, token=token, headers=headers)
                self.assertEqual(result.status_code, status, result.text)
                self.assertEqual(self.state(), before)

        bad_cases = []
        changed = deepcopy(body); changed["expected_revision"] = 2; bad_cases.append((changed, 409))
        changed = deepcopy(body); changed["payload_laudo"]["caminho_arquivo"] = "/tmp/forbidden"; bad_cases.append((changed, 422))
        changed = deepcopy(body); changed["payload_laudo"]["paciente"]["nome"] = "data:image/png;base64,secret"; bad_cases.append((changed, 422))
        changed = deepcopy(body); changed["payload_laudo"]["conteudo"]["conclusao"] = "x" * (513*1024); bad_cases.append((changed, 413))
        changed = deepcopy(body); changed["imagens"]["persistidas"] = [{"id": 71, "ordem": 0}]; bad_cases.append((changed, 409))
        for bad, status in bad_cases:
            with self.subTest(expected=status):
                result = self.post(bad)
                self.assertEqual(result.status_code, status, result.text[:300])
                self.assertEqual(self.state(), before)


    def test_preview_requires_view_permission_even_when_post_edit_is_allowed(self):
        for existing in (False, True):
            with self.subTest(existing=existing):
                self.draft_id=str(uuid4()); self.url=f"/api/v1/laudos/editor-drafts/{self.draft_id}"; self.preview_url=self.url+"/preview"
                self.save(existing=existing)
                with self.sessions() as db:
                    db.query(PapelPermissao).filter_by(papel_id=1,modulo="laudos").update({"visualizar":0})
                    db.commit()
                before=self.state(); statements=[]
                def record(_connection,_cursor,statement,_parameters,_context,_executemany):
                    statements.append(statement.lower())
                event.listen(self.engine,"before_cursor_execute",record)
                try:
                    with patch("app.services.echo_pdf_preview.render_echo_pdf_content") as renderer:
                        result=self.post(self.existing_body() if existing else self.new_body())
                        self.assertEqual(result.status_code,403,result.text)
                        renderer.assert_not_called()
                finally:
                    event.remove(self.engine,"before_cursor_execute",record)
                self.assertFalse(any(f"from {table} " in statement or f"from {table}\n" in statement
                                     for statement in statements for table in ("laudos","pacientes","tutores")))
                self.assertEqual(self.state(),before)
                self.assertEqual(self.client.get("/api/v1/laudos/901/pdf",headers=self.headers()).status_code,403)
                with self.sessions() as db:
                    db.query(PapelPermissao).filter_by(papel_id=1,modulo="laudos").update({"visualizar":1})
                    db.commit()

    def test_catalog_methods_confirmed_cm_and_diastolic_references_match_real_emission(self):
        with self.sessions() as db:
            db.add(ReferenciaEco(especie="Canina",peso_kg=10,lvid_d_min=20,lvid_d_max=33,
                                  ivs_d_min=4,ivs_d_max=8,lvpw_d_min=4,lvpw_d_max=8,
                                  fs_min=20.7,fs_max=51.9,la_ao_min=.8,la_ao_max=1.6))
            db.commit()
        self.save()
        body=self.new_body()
        body["payload_laudo"]["paciente"].update(peso="10",idade="4a")
        body["payload_laudo"]["medidas"]={
            "DIVEd":"3.0","SIVd":".5","PLVEd":".6","DIVES":"1.8",
            **{f"unidade_confirmada_{key}":"cm" for key in ("DIVEd","SIVd","PLVEd","DIVES")},
            "VE_tecnica_relatorio":"modo_m","DeltaD_FS":"40","AE_Ao":"1.41",
            "AE_Ao_metodo":"2d_eixo_curto_diastole_inicial_sueco",
            "Onda_E":".7","Onda_A":".5","E_A":"1.4","TD":"120","TRIV":"70",
            "e_doppler":".08","a_doppler":".1","E_E_linha":"8.75",
            "Diastolica_metodo":"canino_2a6_anos_nao_sedado_pw_apical_fim_fluxo","Diastolica_ondas":"separadas",
            "TDI_metodo":"canino_pw_anel_septal_choi","TDI_ondas":"separadas",
        }
        before=self.state(); response=self.post(body); self.assert_pdf(response)
        self.assertEqual(self.state(),before)
        rendered=text(response.content)
        for expected in ("30.00 mm","5.00 mm","6.00 mm","20.00 - 33.00 mm","Hansson et al. (2002)",
                         "Pereira et al. (2009)","Choi et al. (2013)"):
            self.assertIn(expected,rendered)
        emitted=self.client.post("/api/v1/laudos",json=body["payload_laudo"],headers=self.headers())
        self.assertEqual(emitted.status_code,201,emitted.text)
        self.assert_preview_matches_official(response.content,emitted.json()["id"])
    def test_stale_official_source_and_foreign_or_conflicting_images_rejected(self):
        self.save(existing=True)
        body = self.existing_body()
        for modify in (lambda value: value["imagens"]["persistidas"][0].update(id=73),
                       lambda value: value["imagens"].update(removidas_ids=[71,72])):
            invalid = deepcopy(body); modify(invalid)
            before = self.state()
            result = self.post(invalid)
            self.assertIn(result.status_code, (409,422), result.text)
            self.assertEqual(self.state(), before)
        with self.sessions() as db:
            db.get(Laudo,901).diagnostico = "Outra revisão sintética"
            db.commit()
        before = self.state()
        result = self.post(body)
        self.assertEqual(result.status_code, 409, result.text)
        self.assertEqual(result.json()["detail"]["code"], "SOURCE_CHANGED")
        self.assertEqual(self.state(), before)

    def test_temporary_images_are_bound_readable_unexpired_ordered_and_not_consumed(self):
        with self.sessions() as db:
            db.add_all([
                ImagemTemporaria(id=81, session_id="preview-synthetic-session", nome_arquivo="temp-a.png", conteudo=png(), expira_em=datetime.utcnow()+timedelta(hours=1)),
                ImagemTemporaria(id=82, session_id="preview-synthetic-session", nome_arquivo="temp-b.png", conteudo=png("yellow"), expira_em=datetime.utcnow()+timedelta(hours=1)),
                ImagemTemporaria(id=83, session_id="foreign-session", nome_arquivo="foreign.png", conteudo=png(), expira_em=datetime.utcnow()+timedelta(hours=1)),
            ])
            db.commit()
        self.save(images=[{"tempId":81,"uploaded":True},{"tempId":82,"uploaded":True}])
        body = self.new_body()
        body["imagens"]["temp_config"] = [{"id":81,"ordem":1,"descricao":"Legenda segunda"},
                                            {"id":82,"ordem":0,"descricao":"Legenda primeira"}]
        before = self.state()
        response = self.post(body)
        self.assert_pdf(response)
        self.assertEqual(self.state(), before)
        rendered = text(response.content)
        self.assertLess(rendered.index("Legenda primeira"), rendered.index("Legenda segunda"))
        for mutate in (lambda value: value["imagens"].update(temp_session_id="foreign-session"),
                       lambda value: value["imagens"]["temp_config"][0].update(id=83),
                       lambda value: value["imagens"]["temp_config"].pop()):
            invalid=deepcopy(body); mutate(invalid)
            result=self.post(invalid)
            self.assertEqual(result.status_code,409,result.text)
            self.assertEqual(self.state(),before)
        for field, value in (("expira_em", datetime.utcnow()-timedelta(minutes=1)), ("conteudo", b"broken image")):
            with self.sessions() as db:
                setattr(db.get(ImagemTemporaria,81),field,value)
                db.commit()
            broken_state=self.state()
            result=self.post(body)
            self.assertEqual(result.status_code,409,result.text)
            self.assertEqual(self.state(),broken_state)
            with self.sessions() as db:
                item=db.get(ImagemTemporaria,81); item.expira_em=datetime.utcnow()+timedelta(hours=1); item.conteudo=png(); db.commit()

    def test_render_error_is_sanitized_and_workspace_remains_open(self):
        self.save()
        before=self.state()
        with patch("app.services.echo_pdf_preview.render_echo_pdf_content", side_effect=RuntimeError("sensitive /tmp/private")):
            response=self.post(self.new_body())
        self.assertEqual(response.status_code,500,response.text)
        self.assertNotIn("private",response.text)
        self.assertEqual(self.state(),before)
        self.assertEqual(self.client.get(self.url,headers=self.headers()).status_code,200)

    def test_official_cache_drops_previous_layout_version_without_touching_other_modalities(self):
        # Restored full Stage includes HP, unlike the isolated production PDF.
        # Neither its former cache nor the production-only layout cache is valid.
        with self.sessions() as db:
            db.add(Laudo(id=903, paciente_id=901, veterinario_id=1, tipo="pressao_arterial", titulo="QA"))
            db.commit()
            current_echo = compute_laudo_pdf_cache_key(db, 901, 1)
            current_pressure = compute_laudo_pdf_cache_key(db, 903, 1)
            for previous_version in (
                "2026-10-27-eco-extrapolated-age-note-v32",
                "2026-11-02-eco-reviewed-pulmonary-probability-v33",
                "2026-11-04-eco-reviewed-preview-layout-v34",
                "2026-11-04-eco-full-stage-reviewed-preview-hp-v35",
            ):
                with self.subTest(previous_version=previous_version):
                    with patch("app.services.laudo_pdf_service.LAUDO_PDF_ECO_RENDERER_VERSION", previous_version):
                        self.assertNotEqual(compute_laudo_pdf_cache_key(db, 901, 1), current_echo)
                        self.assertEqual(compute_laudo_pdf_cache_key(db, 903, 1), current_pressure)
            self.assertEqual(render_laudo_pdf(db, 901, db.get(User, 1)).cache_key, current_echo)

    def test_real_pdf_clinical_projections_match_for_2d_feline_fusion_and_hp_review_states(self):
        cases=[]
        mode2d=self.new_body(); mode2d["payload_laudo"]["medidas"]={"DIVEd_2D":"22", "DIVES_2D":"14", "VE_tecnica_relatorio":"2d", "VE_vista_2D":"eixo_curto"}; cases.append(mode2d)
        fusion=self.new_body(); fusion["payload_laudo"]["paciente"]["especie"]="Gato"
        fusion["payload_laudo"]["medidas"]={"Onda_E":"1.08","Onda_A":".95","E_A":"1.14","E_E_linha":"6.75", "Diastolica_ondas":"fundidas", "e_doppler":".16", "TRIV":"40"}; cases.append(fusion)
        for reviewed in (True,False):
            hp=self.new_body()
            measures={"HP_ativa":"sim","HP_TRV":"adequado","HP_VSVD":"sem_obstrucao","IT_Vmax":"3.2",
                      "HP_ventriculos":"com_sinais","HP_arteria_pulmonar":"com_sinais","HP_atrio_cava":"sem_sinais"}
            if reviewed: measures["HP_revisao"]=make_pulmonary_review_stamp(measures,"Canina")
            hp["payload_laudo"]["medidas"]=measures; cases.append(hp)
        for index, body in enumerate(cases):
            with self.subTest(case=index):
                self.draft_id=str(uuid4());self.url=f"/api/v1/laudos/editor-drafts/{self.draft_id}";self.preview_url=self.url+"/preview"
                self.save()
                before=self.state()
                response=self.post(body); self.assert_pdf(response)
                self.assertEqual(self.state(),before)
                emitted=self.client.post("/api/v1/laudos",json=body["payload_laudo"],headers=self.headers())
                self.assertEqual(emitted.status_code,201,emitted.text)
                self.assert_preview_matches_official(response.content,emitted.json()["id"])
                if index==1:
                    self.assertNotIn("1.14",text(response.content)); self.assertIn("fundidas",text(response.content))
                if index==2: self.assertIn("probabilidade ecocardiográfica alta",text(response.content).lower())
                if index==3: self.assertIn("pendente",text(response.content).lower())

    def test_preview_and_official_withhold_ambiguous_pulmonary_ratio(self):
        body = self.new_body()
        measures = {"HP_ativa":"sim", "HP_TRV":"adequado", "HP_VSVD":"sem_obstrucao", "IT_Vmax":"3.0", "HP_ventriculos":"com_sinais", "HP_arteria_pulmonar":"sem_sinais", "HP_atrio_cava":"sem_sinais", "HP_suporte_automatico":"sim", "AP":"2.2", "Ao_nivel_AP":"20", "unidade_confirmada_Ao_nivel_AP":"mm", "DIVEd":"2.2", "SIVd":"1.2", "PLVEd":"1.2"}
        measures["HP_revisao"] = make_pulmonary_review_stamp(measures,"Canina")
        body["payload_laudo"]["medidas"] = measures
        self.save()
        preview = self.post(body); self.assert_pdf(preview)
        content = text(preview.content).lower()
        self.assertIn("confirmar unidade de ap/ao", content)
        self.assertNotRegex(content, r"\bap/ao\s*[:=]?\s*0[.,]11\b")
        self.assertNotIn("probabilidade ecocardiográfica baixa", content)
        emitted = self.client.post("/api/v1/laudos",json=body["payload_laudo"],headers=self.headers())
        self.assertEqual(emitted.status_code,201,emitted.text)
        self.assert_preview_matches_official(preview.content,emitted.json()["id"])


if __name__ == "__main__":
    unittest.main()

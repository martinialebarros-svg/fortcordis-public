# Importação de XML de Ecocardiograma

Esta funcionalidade permite importar arquivos XML de aparelhos de ecocardiograma (Vivid IQ e compatíveis) para preenchimento automático de dados do paciente e medidas ecocardiográficas.

## Funcionalidade

### Backend

- **Parser XML** (`backend/app/utils/xml_parser.py`):
  - Extrai dados do paciente (nome, tutor, espécie, raça, peso, idade, sexo)
  - Extrai medidas ecocardiográficas (Ao, LA, LVIDd, IVSd, EF, FS, etc.)
  - Suporta conversão de lb para kg
  - Normaliza espécies (Canina/Felina)

- **Endpoints API** (`backend/app/api/v1/endpoints/xml_import.py`):
  - `POST /api/v1/xml/importar-eco` - Upload de arquivo XML (multipart/form-data)
  - `POST /api/v1/xml/importar-eco/base64` - Upload via base64

### Frontend

- **Componente XmlUploader** (`frontend/app/laudos/components/XmlUploader.tsx`):
  - Interface drag-and-drop para upload de XML
  - Feedback visual (sucesso/erro)
  - Validação de tipo de arquivo

- **Página Novo Laudo** (`frontend/app/laudos/novo/page.tsx`):
  - Layout com upload XML à esquerda
  - Formulário de paciente, medidas e conteúdo do laudo
  - Preenchimento automático dos campos ao importar XML

## Uso

1. Acesse **Laudos e Exames > Novo Laudo**
2. Arraste o arquivo XML do aparelho de ecocardiograma ou clique para selecionar
3. Os dados serão preenchidos automaticamente nos campos:
   - Dados do paciente (nome, tutor, espécie, raça, peso, idade, sexo)
   - Medidas ecocardiográficas
   - Clínica
4. Revise e complete os dados necessários
5. Salve o laudo

## Formatos Suportados

- Arquivos XML exportados do aparelho **Vivid IQ**
- Tags suportadas:
  - `lastName`, `firstName` - Nome do tutor e paciente
  - `Species`, `Category` - Espécie (C/F)
  - `weight`, `patientWeight` - Peso
  - `StudyDate`, `ExamDate` - Data do exame
  - `HeartRate` - Frequência cardíaca
  - Parâmetros de medidas ecocardiográficas

## Instalação

As dependências já foram adicionadas ao `requirements.txt`:
```bash
beautifulsoup4==4.12.2
lxml==4.9.3
```

Instale com:
```bash
pip install -r requirements.txt
```

## Exemplo de Resposta da API

```json
{
  "success": true,
  "dados": {
    "paciente": {
      "nome": "Rex",
      "tutor": "João Silva",
      "raca": "SRD",
      "especie": "Canina",
      "peso": "10.5",
      "idade": "5 anos",
      "sexo": "Macho",
      "telefone": "",
      "data_exame": "2024-01-15"
    },
    "medidas": {
      "Ao": 2.1,
      "LA": 2.3,
      "LVIDd": 3.8,
      "EF": 65.0,
      "FS": 35.0
    },
    "clinica": "Clínica Veterinária ABC",
    "veterinario_solicitante": "",
    "fc": "120"
  },
  "filename": "exame_12345.xml"
}
```

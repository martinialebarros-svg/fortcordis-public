"""Endereço completo do estabelecimento para documentos contábeis."""
import re
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EnderecoFiscal(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    cnpj: str = Field(min_length=14, max_length=18)
    endereco: str = Field(min_length=1, max_length=255)
    numero: str = Field(min_length=1, max_length=30)
    complemento: str = Field(default="", max_length=255)
    bairro: str = Field(min_length=1, max_length=150)
    cidade: str = Field(min_length=1, max_length=150)
    estado: str = Field(min_length=2, max_length=2)
    cep: str = Field(min_length=8, max_length=9)
    fonte_url: str = Field(min_length=1, max_length=1000)

    @field_validator("cnpj")
    @classmethod
    def documento(cls, value):
        value = re.sub(r"[.\s/\-]", "", value.upper())
        if not re.fullmatch(r"[A-Z0-9]{12}[0-9]{2}", value):
            raise ValueError("CNPJ inválido.")
        return value

    @field_validator("cep")
    @classmethod
    def codigo_postal(cls, value):
        if not re.fullmatch(r"[0-9]{5}-?[0-9]{3}", value):
            raise ValueError("Informe os oito dígitos do CEP fiscal.")
        return value.replace("-", "")

    @field_validator("estado")
    @classmethod
    def uf(cls, value):
        value = value.upper()
        if value not in "AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split():
            raise ValueError("UF inválida.")
        return value

    @field_validator("fonte_url")
    @classmethod
    def fonte(cls, value):
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Informe o link HTTPS da fonte consultada.")
        return value

"use client";

import { useEffect, useState } from "react";
import { X, DollarSign, Calendar, FileText, Tag, CreditCard } from "lucide-react";
import api from "@/lib/axios";
import { extractApiErrorMessageSync } from "@/lib/api-error";
import {
  calendarDateInput,
  calendarDateToOperationalIso,
  operationalTodayDateInput,
} from "@/lib/calendar-date";

interface TransacaoModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
  transacao?: any;
}

const CATEGORIAS_ENTRADA = [
  { id: "consulta", nome: "Consulta" },
  { id: "exame", nome: "Exame" },
  { id: "cirurgia", nome: "Cirurgia" },
  { id: "medicamento", nome: "Medicamento" },
  { id: "banho_tosa", nome: "Banho e Tosa" },
  { id: "produto", nome: "Produto" },
  { id: "outros", nome: "Outros" },
];

const CATEGORIAS_SAIDA = [
  { id: "salario", nome: "Salário" },
  { id: "aluguel", nome: "Aluguel" },
  { id: "fornecedor", nome: "Fornecedor" },
  { id: "imposto", nome: "Imposto" },
  { id: "manutencao", nome: "Manutenção" },
  { id: "marketing", nome: "Marketing" },
  { id: "outros", nome: "Outros" },
];

const FORMAS_PAGAMENTO = [
  { id: "dinheiro", nome: "Dinheiro" },
  { id: "cartao_credito", nome: "Cartão de Crédito" },
  { id: "cartao_debito", nome: "Cartão de Débito" },
  { id: "pix", nome: "PIX" },
  { id: "boleto", nome: "Boleto" },
  { id: "transferencia", nome: "Transferência" },
];

const STATUS_OPTIONS = [
  { id: "Pendente", nome: "Pendente" },
  { id: "Pago", nome: "Pago" },
  { id: "Recebido", nome: "Recebido" },
  { id: "Cancelado", nome: "Cancelado" },
];

export default function TransacaoModal({ isOpen, onClose, onSuccess, transacao }: TransacaoModalProps) {
  const [loading, setLoading] = useState(false);
  const [pacientes, setPacientes] = useState<any[]>([]);
  const isEditando = !!transacao;

  const [formData, setFormData] = useState({
    tipo: "entrada",
    categoria: "consulta",
    valor: "",
    desconto: "0",
    forma_pagamento: "dinheiro",
    status: "Pendente",
    descricao: "",
    data_transacao: "",
    data_vencimento: "",
    observacoes: "",
    paciente_id: "",
    paciente_nome: "",
    parcelas: "1",
  });

  // Preencher formulário quando estiver editando
  useEffect(() => {
    if (isEditando && transacao) {
      const dataTransacao = transacao.data_transacao
        ? calendarDateInput(transacao.data_transacao)
        : operationalTodayDateInput();
      
      const dataVencimento = transacao.data_vencimento
        ? calendarDateInput(transacao.data_vencimento)
        : "";

      setFormData({
        tipo: transacao.tipo || "entrada",
        categoria: transacao.categoria || "consulta",
        valor: transacao.valor ? transacao.valor.toString() : "",
        desconto: transacao.desconto ? transacao.desconto.toString() : "0",
        forma_pagamento: transacao.forma_pagamento || "dinheiro",
        status: transacao.status || "Pendente",
        descricao: transacao.descricao || "",
        data_transacao: dataTransacao,
        data_vencimento: dataVencimento,
        observacoes: transacao.observacoes || "",
        paciente_id: transacao.paciente_id?.toString() || "",
        paciente_nome: transacao.paciente_nome || "",
        parcelas: transacao.parcelas?.toString() || "1",
      });
    } else {
      setFormData({
        tipo: "entrada",
        categoria: "consulta",
        valor: "",
        desconto: "0",
        forma_pagamento: "dinheiro",
        status: "Pendente",
        descricao: "",
        data_transacao: operationalTodayDateInput(),
        data_vencimento: "",
        observacoes: "",
        paciente_id: "",
        paciente_nome: "",
        parcelas: "1",
      });
    }
  }, [transacao, isEditando, isOpen]);

  // Carregar pacientes
  useEffect(() => {
    if (isOpen) {
      carregarPacientes();
    }
  }, [isOpen]);

  const carregarPacientes = async () => {
    try {
      const response = await api.get("/pacientes?limit=1000");
      setPacientes(response.data.items || []);
    } catch (error) {
      console.error("Erro ao carregar pacientes:", error);
    }
  };

  const handlePacienteChange = (pacienteId: string) => {
    const paciente = pacientes.find(p => p.id.toString() === pacienteId);
    setFormData({
      ...formData,
      paciente_id: pacienteId,
      paciente_nome: paciente?.nome || ""
    });
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);

    try {
      const valor = parseFloat(formData.valor);
      const desconto = parseFloat(formData.desconto) || 0;
      
      const payload = {
        tipo: formData.tipo,
        categoria: formData.categoria,
        valor: valor,
        desconto: desconto,
        forma_pagamento: formData.forma_pagamento,
        status: formData.status,
        descricao: formData.descricao,
        data_transacao: calendarDateToOperationalIso(formData.data_transacao),
        data_vencimento: calendarDateToOperationalIso(formData.data_vencimento),
        observacoes: formData.observacoes || null,
        paciente_id: formData.paciente_id ? parseInt(formData.paciente_id) : null,
        paciente_nome: formData.paciente_nome || null,
        parcelas: parseInt(formData.parcelas) || 1,
      };

      if (isEditando) {
        await api.put(`/financeiro/transacoes/${transacao.id}`, payload);
      } else {
        await api.post("/financeiro/transacoes", payload);
      }

      onSuccess();
      onClose();
    } catch (error) {
      console.error("Erro ao salvar transação:", error);
      alert(`Erro ao salvar transação: ${extractApiErrorMessageSync(error, "Falha ao salvar transação.")}`);
    } finally {
      setLoading(false);
    }
  };

  const categorias = formData.tipo === "entrada" ? CATEGORIAS_ENTRADA : CATEGORIAS_SAIDA;
  const valorFinal = (parseFloat(formData.valor) || 0) - (parseFloat(formData.desconto) || 0);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-40 p-4">
      <div className="bg-white rounded-lg w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <div className="flex justify-between items-center p-6 border-b">
          <h2 className="text-xl font-semibold">
            {isEditando ? "Editar Transação" : "Nova Transação"}
          </h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X className="w-6 h-6" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {/* Tipo */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Tipo</label>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setFormData({ ...formData, tipo: "entrada", categoria: "consulta" })}
                className={`flex-1 py-2 px-4 rounded-lg border font-medium ${
                  formData.tipo === "entrada"
                    ? "bg-green-100 border-green-500 text-green-700"
                    : "bg-white border-gray-300 text-gray-700 hover:bg-gray-50"
                }`}
              >
                Entrada (+)
              </button>
              <button
                type="button"
                onClick={() => setFormData({ ...formData, tipo: "saida", categoria: "salario" })}
                className={`flex-1 py-2 px-4 rounded-lg border font-medium ${
                  formData.tipo === "saida"
                    ? "bg-red-100 border-red-500 text-red-700"
                    : "bg-white border-gray-300 text-gray-700 hover:bg-gray-50"
                }`}
              >
                Saída (-)
              </button>
            </div>
          </div>

          {/* Descrição */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              <FileText className="w-4 h-4 inline mr-1" />
              Descrição *
            </label>
            <input
              type="text"
              required
              value={formData.descricao}
              onChange={(e) => setFormData({ ...formData, descricao: e.target.value })}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-transparent"
              placeholder="Ex: Consulta cardiologia - Rex"
            />
          </div>

          {/* Categoria */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              <Tag className="w-4 h-4 inline mr-1" />
              Categoria
            </label>
            <select
              value={formData.categoria}
              onChange={(e) => setFormData({ ...formData, categoria: e.target.value })}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-transparent"
            >
              {categorias.map((cat) => (
                <option key={cat.id} value={cat.id}>
                  {cat.nome}
                </option>
              ))}
            </select>
          </div>

          {/* Valores */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                <DollarSign className="w-4 h-4 inline mr-1" />
                Valor (R$) *
              </label>
              <input
                type="number"
                step="0.01"
                min="0.01"
                required
                value={formData.valor}
                onChange={(e) => setFormData({ ...formData, valor: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-transparent"
                placeholder="0,00"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Desconto (R$)</label>
              <input
                type="number"
                step="0.01"
                min="0"
                value={formData.desconto}
                onChange={(e) => setFormData({ ...formData, desconto: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-transparent"
                placeholder="0,00"
              />
            </div>
          </div>

          {/* Valor Final */}
          <div className="bg-gray-50 p-3 rounded-lg">
            <span className="text-sm text-gray-600">Valor Final: </span>
            <span className={`font-bold ${formData.tipo === "entrada" ? "text-green-600" : "text-red-600"}`}>
              {formData.tipo === "entrada" ? "+" : "-"} R$ {valorFinal.toFixed(2)}
            </span>
          </div>

          {/* Forma de Pagamento e Status */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                <CreditCard className="w-4 h-4 inline mr-1" />
                Forma de Pagamento
              </label>
              <select
                value={formData.forma_pagamento}
                onChange={(e) => setFormData({ ...formData, forma_pagamento: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-transparent"
              >
                {FORMAS_PAGAMENTO.map((fp) => (
                  <option key={fp.id} value={fp.id}>
                    {fp.nome}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Status</label>
              <select
                value={formData.status}
                onChange={(e) => setFormData({ ...formData, status: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-transparent"
              >
                {STATUS_OPTIONS.map((st) => (
                  <option key={st.id} value={st.id}>
                    {st.nome}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Datas */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                <Calendar className="w-4 h-4 inline mr-1" />
                Data da Transação
              </label>
              <input
                type="date"
                required
                value={formData.data_transacao}
                onChange={(e) => setFormData({ ...formData, data_transacao: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-transparent"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Data de Vencimento</label>
              <input
                type="date"
                value={formData.data_vencimento}
                onChange={(e) => setFormData({ ...formData, data_vencimento: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-transparent"
              />
            </div>
          </div>

          {/* Paciente */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Paciente (opcional)</label>
            <select
              value={formData.paciente_id}
              onChange={(e) => handlePacienteChange(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-transparent"
            >
              <option value="">Selecione um paciente...</option>
              {pacientes.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.nome} {p.tutor ? `(Tutor: ${p.tutor})` : ""}
                </option>
              ))}
            </select>
          </div>

          {/* Parcelas */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Número de Parcelas</label>
            <input
              type="number"
              min="1"
              max="24"
              value={formData.parcelas}
              onChange={(e) => setFormData({ ...formData, parcelas: e.target.value })}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-transparent"
            />
          </div>

          {/* Observações */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Observações</label>
            <textarea
              value={formData.observacoes}
              onChange={(e) => setFormData({ ...formData, observacoes: e.target.value })}
              rows={3}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-transparent"
              placeholder="Observações adicionais..."
            />
          </div>

          {/* Botões */}
          <div className="flex justify-end gap-3 pt-4 border-t">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-gray-600 hover:text-gray-900 border border-gray-300 rounded-lg hover:bg-gray-50"
            >
              Cancelar
            </button>
            <button
              type="submit"
              disabled={loading}
              className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50 flex items-center gap-2"
            >
              {loading ? (
                <>
                  <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  Salvando...
                </>
              ) : (
                <>{isEditando ? "Atualizar" : "Salvar"}</>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

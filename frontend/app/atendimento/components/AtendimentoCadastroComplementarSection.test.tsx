import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AtendimentoCadastroComplementarSection from "./AtendimentoCadastroComplementarSection";

const mocks = vi.hoisted(() => ({ revisao: vi.fn() }));
vi.mock("@/components/TutorRevisaoCadastro", () => ({ default: (props: { tutorId: number }) => {
  mocks.revisao(props); return <div data-testid="revisao-tutor">Revisão tutor #{props.tutorId}</div>;
} }));

function props() {
  return {
    cadastroComplementar: { paciente: { id: 11, nome: "Pingo", tutor_id: 23 }, tutor: { id: 23, nome: "Cristiane", identificacao_pendente: true } },
    cadastroComplementarExpandido: false, cadastroComplementarPendencias: ["identificação do tutor", "telefone"],
    carregandoCadastroComplementar: false, salvandoCadastroComplementar: false,
    revisaoTutorDisponivel: true, form: { paciente_id: "11" },
    especieCadastroAtual: "", especieRacaExibicao: "", idadePacienteExibicao: "", novaRacaCadastro: "", opcoesRacaCadastro: [],
    setCadastroComplementarExpandido: vi.fn(), salvarCadastroComplementarAtual: vi.fn(),
    setCadastroPacienteField: vi.fn(), setCadastroTutorField: vi.fn(), setNovaRacaCadastro: vi.fn(),
    setStatusCepTutor: vi.fn(), handleAdicionarRacaCadastro: vi.fn(), consultarCepTutor: vi.fn(),
    sincronizarPesoCadastroNaTriagem: vi.fn(), onRevisaoTutorUpdated: vi.fn(),
  };
}

describe("Revisão de identidade na complementação do atendimento", () => {
  beforeEach(() => vi.clearAllMocks());

  it("não monta a revisão nem exige preenchimento quando o cadastro está recolhido", () => {
    render(<AtendimentoCadastroComplementarSection {...props()} />);
    expect(mocks.revisao).not.toHaveBeenCalled();
    expect(screen.getByText(/A pendência não impede continuar o atendimento/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Salvar cadastro" })).not.toBeInTheDocument();
  });

  it("usa somente o ID do tutor vinculado ao expandir, mesmo com nome incompleto", () => {
    render(<AtendimentoCadastroComplementarSection {...props()} cadastroComplementarExpandido />);
    expect(screen.getByTestId("revisao-tutor")).toHaveTextContent("#23");
    expect(mocks.revisao).toHaveBeenCalledWith(expect.objectContaining({ tutorId: 23 }));
    expect(screen.getByRole("button", { name: "Salvar cadastro" })).toBeEnabled();
  });

  it("preserva os campos editáveis e pede salvar somente antes da revisão da identidade", () => {
    const state = props();
    render(<AtendimentoCadastroComplementarSection {...state} cadastroComplementarExpandido revisaoTutorDisponivel={false} />);
    expect(mocks.revisao).not.toHaveBeenCalled();
    expect(screen.getByText("Salve as alterações cadastrais abaixo antes de revisar a identificação do tutor.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Salvar cadastro" })).toBeEnabled();
    fireEvent.change(screen.getByPlaceholderText("Nome do pet"), { target: { value: "Pingo atualizado" } });
    expect(state.setCadastroPacienteField).toHaveBeenCalledWith("nome", "Pingo atualizado");
    fireEvent.change(screen.getByPlaceholderText("Nome do tutor"), { target: { value: "Cristiane Silva" } });
    expect(state.setCadastroTutorField).toHaveBeenCalledWith("nome", "Cristiane Silva");
  });

  it("não monta revisão de identidade enquanto carrega a troca de paciente", () => {
    render(<AtendimentoCadastroComplementarSection {...props()} cadastroComplementarExpandido carregandoCadastroComplementar />);
    expect(mocks.revisao).not.toHaveBeenCalled();
    expect(screen.getByText("Carregando dados atuais do paciente e do tutor...")).toBeInTheDocument();
  });

  it("não oferece revisão do tutor anterior se a troca de paciente deixou dados antigos na tela", () => {
    render(<AtendimentoCadastroComplementarSection {...props()} cadastroComplementarExpandido form={{ paciente_id: "99" }} />);
    expect(mocks.revisao).not.toHaveBeenCalled();
    expect(screen.queryByTestId("revisao-tutor")).not.toBeInTheDocument();
  });
});

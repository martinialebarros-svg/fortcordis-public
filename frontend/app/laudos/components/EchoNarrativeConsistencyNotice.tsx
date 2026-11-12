import { findEchoNarrativeDiscrepancies } from "@/lib/echo-narrative-consistency";

type Props = {
  measurements: Record<string, string>;
  qualitative: object;
  conclusion: string;
  species?: string;
};

export default function EchoNarrativeConsistencyNotice({ measurements, qualitative, conclusion, species }: Props) {
  const discrepancies = findEchoNarrativeDiscrepancies(measurements, qualitative, conclusion, species);
  if (!discrepancies.length) return null;
  return (
    <div role="status" aria-label="Conferência de coerência do laudo" data-echo-consistency-review
      className="mb-4 min-w-0 break-words rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
      <strong>Confira a coerência do laudo antes de emitir o PDF</strong>
      <ul className="mt-1 list-disc space-y-1 pl-5">
        {discrepancies.map((item) => <li key={item.key}>
          <p>{item.message}</p>
          {item.excerpt && (
            <details className="mt-1 text-xs">
              <summary className="cursor-pointer font-medium">Ver trecho{item.section ? ` · ${item.section}` : ""} e sugestão</summary>
              <blockquote className="mt-2 whitespace-pre-wrap border-l-2 border-amber-300 pl-2">{item.excerpt}</blockquote>
              {item.suggestion && <p className="mt-2"><strong>Sugestão para sua revisão:</strong> {item.suggestion}</p>}
            </details>
          )}
        </li>)}
      </ul>
      <p className="mt-2 text-xs">Aviso de conferência. A interpretação e o salvamento permanecem sob sua decisão.</p>
    </div>
  );
}

import type { ClinicalPendingField, ClinicalPendingItem } from "@/lib/atendimento-clinical-notes";

export default function AtendimentoPendenciasClinicas({
  items,
  onNavigate,
}: {
  items: ClinicalPendingItem[];
  onNavigate: (field: ClinicalPendingField) => void;
}) {
  return (
    <ul className="mt-3 space-y-1 text-sm text-amber-900">
      {items.map(({ field, label }) => (
        <li key={field}>
          <button
            type="button"
            onClick={() => onNavigate(field)}
            className="min-h-8 rounded-md px-1 text-left font-medium underline underline-offset-2 hover:bg-amber-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-amber-700"
          >
            {label}
          </button>
        </li>
      ))}
    </ul>
  );
}

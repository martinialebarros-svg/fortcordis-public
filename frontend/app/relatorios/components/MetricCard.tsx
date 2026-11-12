import { LucideIcon } from "lucide-react";

interface MetricCardProps {
  titulo: string;
  valor: string;
  descricao?: string;
  icon?: LucideIcon;
  iconColorClass?: string;
  emphasis?: "neutral" | "positive" | "negative";
}

export default function MetricCard({
  titulo,
  valor,
  descricao,
  icon: Icon,
  iconColorClass = "text-blue-600",
  emphasis = "neutral",
}: MetricCardProps) {
  const valorClass =
    emphasis === "positive"
      ? "text-green-700"
      : emphasis === "negative"
        ? "text-red-700"
        : "text-gray-900";

  return (
    <div className={`fc-reports-metric fc-reports-metric-${emphasis}`}>
      <div className="flex items-center justify-between mb-1">
        <span className="text-sm text-gray-600">{titulo}</span>
        {Icon ? <Icon className={`w-4 h-4 ${iconColorClass}`} /> : null}
      </div>
      <p className={`text-2xl font-bold ${valorClass}`}>{valor}</p>
      {descricao ? <p className="text-xs text-gray-500 mt-1">{descricao}</p> : null}
    </div>
  );
}

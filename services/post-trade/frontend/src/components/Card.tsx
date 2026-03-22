interface CardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  positive?: boolean;
}

export function Card({ title, value, subtitle, positive }: CardProps) {
  const color = positive === undefined ? 'text-white' : positive ? 'text-emerald-400' : 'text-red-400';
  return (
    <div className="bg-gray-900 rounded-lg p-4 border border-gray-800">
      <div className="text-xs text-gray-400 uppercase tracking-wide mb-1">{title}</div>
      <div className={`text-xl font-semibold ${color}`}>{value}</div>
      {subtitle && <div className="text-xs text-gray-500 mt-1">{subtitle}</div>}
    </div>
  );
}

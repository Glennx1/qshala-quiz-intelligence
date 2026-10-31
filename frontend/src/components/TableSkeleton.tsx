// Shimmer skeleton for table-shaped loading states (QShala priority plan P2-5). Shows the
// shape of the content that's about to load instead of a bare spinner, so the page reads as
// "almost ready" rather than "nothing is happening yet."
interface Props {
  columns: number;
  rows?: number;
}

export default function TableSkeleton({ columns, rows = 8 }: Props) {
  return (
    <table className="w-full text-left text-[13px] border-collapse">
      <tbody className="divide-y divide-slate-100">
        {Array.from({ length: rows }).map((_, rowIdx) => (
          <tr key={rowIdx}>
            {Array.from({ length: columns }).map((_, colIdx) => (
              <td key={colIdx} className="py-3.5 px-4">
                <div
                  className="h-4 animate-pulse rounded bg-slate-100"
                  style={{ width: colIdx === 0 ? '70%' : `${45 + ((rowIdx + colIdx) % 3) * 15}%` }}
                />
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

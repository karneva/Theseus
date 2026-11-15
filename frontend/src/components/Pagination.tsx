interface PaginationProps {
  page: number;
  totalPages: number;
  totalElements: number;
  onPageChange: (newPage: number) => void;
  itemName?: string;
}

export function Pagination({
  page,
  totalPages,
  totalElements,
  onPageChange,
  itemName = 'items',
}: PaginationProps) {
  return (
    <div className="flex h-[65px] shrink-0 items-center justify-between border-t border-[rgba(65,71,81,0.1)] px-4">
      <span className="text-xs text-white/40">
        Total {totalElements} {itemName}
      </span>
      <div className="flex items-center gap-1">
        <button
          disabled={page === 0}
          onClick={() => onPageChange(page - 1)}
          className="px-2 py-1 text-xs text-white/60 hover:text-white disabled:opacity-50"
        >
          Prev
        </button>
        <span className="px-2 text-xs text-white/60">
          {page + 1} / {totalPages || 1}
        </span>
        <button
          disabled={page >= (totalPages || 1) - 1}
          onClick={() => onPageChange(page + 1)}
          className="px-2 py-1 text-xs text-white/60 hover:text-white disabled:opacity-50"
        >
          Next
        </button>
      </div>
    </div>
  );
}

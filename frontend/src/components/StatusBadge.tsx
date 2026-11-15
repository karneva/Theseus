import { cn } from '@/lib/utils';

interface StatusBadgeProps {
  status: 'ACTIVE' | 'INACTIVE';
  className?: string;
}

export function StatusBadge({ status, className }: StatusBadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center justify-center rounded-[2px] border px-[9px] py-[3px] text-[10px] font-bold uppercase',
        status === 'ACTIVE'
          ? 'border-[rgba(34,197,94,0.2)] bg-[rgba(34,197,94,0.1)] text-[#4ade80]'
          : 'border-[rgba(239,68,68,0.2)] bg-[rgba(239,68,68,0.1)] text-[#f87171]',
        className,
      )}
    >
      {status}
    </span>
  );
}

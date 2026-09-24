import { orderStatusLabel, statusTone } from "@/lib/format";

export function OrderStatus({ value }: { value: string }) {
  return (
    <span className={`status tone-${statusTone(value)}`}>
      {orderStatusLabel(value)}
    </span>
  );
}

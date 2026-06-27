import type { ReactNode } from "react";
import type {
  WorkflowResultPresentation,
  WorkflowResultPresentationField,
} from "@/types/workflow";

function asText(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function formatResultValue(field: WorkflowResultPresentationField): ReactNode {
  const { value, format } = field;
  switch (format) {
    case "currency": {
      const num = Number(value);
      return Number.isFinite(num)
        ? new Intl.NumberFormat(undefined, { style: "currency", currency: "USD" }).format(num)
        : asText(value);
    }
    case "number": {
      const num = Number(value);
      return Number.isFinite(num) ? new Intl.NumberFormat().format(num) : asText(value);
    }
    case "datetime": {
      const date = new Date(asText(value));
      return Number.isNaN(date.getTime()) ? asText(value) : date.toLocaleString();
    }
    case "url": {
      const href = asText(value);
      return (
        <a
          href={href}
          target="_blank"
          rel="noreferrer"
          className="text-conduut-500 underline underline-offset-2 break-all"
        >
          {href}
        </a>
      );
    }
    case "email": {
      const email = asText(value);
      return (
        <a href={`mailto:${email}`} className="text-conduut-500 underline underline-offset-2">
          {email}
        </a>
      );
    }
    case "boolean":
      return value ? "✓ Evet" : "✗ Hayır";
    case "list": {
      const items = Array.isArray(value) ? value : [value];
      return (
        <div className="flex flex-wrap gap-1.5">
          {items.map((item, index) => (
            <span
              key={index}
              className="rounded-md bg-muted px-2 py-0.5 text-[12.5px] text-foreground"
            >
              {asText(item)}
            </span>
          ))}
        </div>
      );
    }
    case "longtext":
      return <span className="whitespace-pre-wrap break-words">{asText(value)}</span>;
    default:
      return asText(value);
  }
}

export function WorkflowResultView({
  presentation,
}: {
  presentation: WorkflowResultPresentation;
}) {
  return (
    <div className="rounded-md border border-border bg-muted/30 p-4">
      {presentation.title && (
        <p className="mb-3 text-[14px] font-medium text-foreground">{presentation.title}</p>
      )}
      <dl className="grid gap-3 sm:grid-cols-2">
        {presentation.fields.map((field, index) => (
          <div key={`${field.label}-${index}`} className="min-w-0">
            <dt className="text-[12px] uppercase tracking-wide text-muted-foreground">
              {field.label}
            </dt>
            <dd className="mt-0.5 text-[14px] text-foreground break-words">
              {formatResultValue(field)}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

"use client";
// A form that runs a server action and shows its error above the fields.
// Works without JavaScript too (the page reloads with the result); with it,
// the page doesn't reload and buttons say "Working…" while it runs.
import { useActionState } from "react";
import { useFormStatus } from "react-dom";

import type { FormState } from "@/lib/forms";

type Props = {
  action: (state: FormState, data: FormData) => Promise<FormState>;
  children: React.ReactNode;
  className?: string;
  "aria-label"?: string;
};

export function ActionForm({ action, children, className, ...rest }: Props) {
  const [state, formAction] = useActionState(action, {});
  return (
    <form action={formAction} className={className} aria-label={rest["aria-label"]}>
      {state.error ? (
        <div className="notice notice-error" role="alert">
          {state.error}
        </div>
      ) : null}
      {state.done ? (
        <div className="notice notice-done" role="status">
          {state.done}
        </div>
      ) : null}
      {children}
    </form>
  );
}

/** A submit button that is disabled while its form's action runs. */
export function SubmitButton({
  children,
  className = "btn btn-primary",
  disabled,
  name,
  value,
}: {
  children: React.ReactNode;
  className?: string;
  disabled?: boolean;
  name?: string;
  value?: string;
}) {
  const { pending } = useFormStatus();
  return (
    <button type="submit" className={className} disabled={disabled || pending} name={name} value={value}>
      {pending ? "Working…" : children}
    </button>
  );
}

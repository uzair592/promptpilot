"use client";

import { useId, useMemo, useState } from "react";

export function ModelPicker({
  label = "Model",
  models,
  value,
  onChange,
  disabled = false,
  required = true,
}: {
  label?: string;
  models: string[];
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  required?: boolean;
}) {
  const id = useId();
  const [search, setSearch] = useState("");
  const [manual, setManual] = useState(false);
  const available = useMemo(() => [...new Set(models)].sort(), [models]);
  const filtered = available.filter((model) =>
    model.toLowerCase().includes(search.toLowerCase()),
  );
  const useInput = manual || !available.length;
  return (
    <div className="model-picker">
      <label htmlFor={id}>{label}</label>
      {!useInput && available.length > 8 && (
        <input
          type="search"
          aria-label={`Search ${label.toLowerCase()}`}
          placeholder={`Search ${available.length} available models…`}
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          disabled={disabled}
        />
      )}
      {useInput ? (
        <input
          id={id}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder="Paste the model ID from your provider"
          disabled={disabled}
          required={required}
          maxLength={240}
          autoComplete="off"
        />
      ) : (
        <select
          id={id}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          disabled={disabled}
          required={required}
        >
          <option value="">Choose a model</option>
          {value && !filtered.includes(value) && (
            <option value={value}>{value}</option>
          )}
          {filtered.map((model) => (
            <option key={model} value={model}>
              {model}
            </option>
          ))}
        </select>
      )}
      <div className="model-picker-note">
        <span>
          {available.length
            ? `${filtered.length} models${search ? " matching your search" : " available"}`
            : "Load your provider’s models, or enter an exact model ID."}
        </span>
        {available.length > 0 && (
          <button
            type="button"
            onClick={() => setManual(!manual)}
            disabled={disabled}
          >
            {manual ? "Choose from list" : "Enter model ID"}
          </button>
        )}
      </div>
    </div>
  );
}

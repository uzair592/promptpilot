"use client";

import { FormEvent, useState } from "react";
import { ModelPicker } from "../../../../components/ModelPicker";
import {
  ProviderConnection,
  ProviderDefinition,
  addProviderConnection,
  discoverProviderModels,
  testProviderConnection,
  disableProvider,
  updateProviderKey,
  updateProviderModel,
} from "../../../../lib/orchestration";

export function ConnectionVault({
  catalog,
  connections,
  canWrite,
  onRefresh,
  onConnected,
}: {
  catalog: ProviderDefinition[];
  connections: ProviderConnection[];
  canWrite: boolean;
  onRefresh: () => Promise<void>;
  onConnected?: (connection: ProviderConnection) => void;
}) {
  const [provider, setProvider] = useState("openrouter");
  const [label, setLabel] = useState("");
  const [model, setModel] = useState("openrouter/free");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [models, setModels] = useState<string[]>([]);
  const [freeOnly, setFreeOnly] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [pendingId, setPendingId] = useState<string | null>(null);
  const selectedProvider = catalog.find((item) => item.id === provider);
  async function act(key: string, action: () => Promise<void>) {
    if (busy) return;
    setBusy(key);
    setError("");
    setNotice("");
    try {
      await action();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Connection failed");
    } finally {
      await onRefresh().catch(() => undefined);
      setBusy("");
    }
  }
  function changeProvider(id: string) {
    setProvider(id);
    setModel(catalog.find((item) => item.id === id)?.default_model || "");
    setModels([]);
    setFreeOnly(false);
    setLabel("");
    setApiKey("");
    setPendingId(null);
    setError("");
    setNotice("");
  }
  function submit(event: FormEvent) {
    event.preventDefault();
    void act("save", async () => {
      const baseLabel = `${selectedProvider?.label || provider} connection`;
      let automaticLabel = baseLabel;
      for (
        let count = 2;
        connections.some(
          (item) => item.provider === provider && item.label === automaticLabel,
        );
        count += 1
      )
        automaticLabel = `${baseLabel} ${count}`;
      const saved = pendingId
        ? await updateProviderModel(pendingId, model)
        : await addProviderConnection({
            provider,
            label: label.trim() || automaticLabel,
            default_model: model,
            api_key: apiKey,
            ...(provider === "custom" ? { base_url: baseUrl } : {}),
          });
      setPendingId(saved.id);
      if (pendingId && apiKey.trim()) await updateProviderKey(saved.id, apiKey);
      setApiKey("");
      const tested = await testProviderConnection(saved.id);
      setPendingId(null);
      setLabel("");
      onConnected?.(tested.connection);
      setNotice(
        `${tested.connection.label} is connected. Choose it in chat or assign its models to your team.`,
      );
    });
  }
  const visibleModels = models.filter(
    (item) => !freeOnly || item.endsWith(":free") || item === "openrouter/free",
  );
  const choices =
    provider === "openrouter" && models.length
      ? [...visibleModels, "openrouter/free"]
      : visibleModels;
  return (
    <div className="connections-hub">
      <ol className="connection-steps" aria-label="Connect an AI model">
        <li className="current">
          <b>1</b>
          <span>
            Choose provider<small>Use your own account</small>
          </span>
        </li>
        <li className={apiKey || pendingId ? "current" : ""}>
          <b>2</b>
          <span>
            Add API key<small>Stored encrypted</small>
          </span>
        </li>
        <li className={models.length ? "current" : ""}>
          <b>3</b>
          <span>
            Select model<small>Connect and start</small>
          </span>
        </li>
      </ol>
      {error && (
        <p className="workflow-alert error" role="alert">
          {error}
        </p>
      )}
      {notice && (
        <p className="workflow-alert success" role="status">
          {notice}
        </p>
      )}
      <div className="vault-layout">
        <section className="connect-provider-panel">
          <div className="panel-heading">
            <div>
              <small>ADD YOUR AI</small>
              <h3>Connect a provider</h3>
            </div>
            <span className="secure-label">Encrypted keys</span>
          </div>
          <form className="workflow-form" onSubmit={submit}>
            <label>
              Provider
              <select
                aria-label="Provider"
                value={provider}
                onChange={(event) => changeProvider(event.target.value)}
                disabled={Boolean(busy)}
              >
                {catalog.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.label}
                  </option>
                ))}
              </select>
            </label>
            <div className={`provider-summary provider-${provider}`}>
              <span>
                {provider === "openrouter"
                  ? "OR"
                  : selectedProvider?.label.slice(0, 2) || "AI"}
              </span>
              <div>
                <strong>
                  {selectedProvider?.label || "Loading providers…"}
                </strong>
                <small>
                  {provider === "openrouter"
                    ? "Many providers with one key · free models available"
                    : "Your account, your models, your choice"}
                </small>
              </div>
            </div>
            {provider === "custom" && (
              <label>
                API base URL
                <input
                  type="url"
                  value={baseUrl}
                  onChange={(event) => setBaseUrl(event.target.value)}
                  placeholder="https://your-provider.com/v1"
                  required
                  disabled={Boolean(busy) || Boolean(pendingId)}
                />
                <span className="field-note">
                  Public HTTPS API with OpenAI-compatible chat completions.
                </span>
              </label>
            )}
            <label>
              Connection name <span className="optional-label">optional</span>
              <input
                value={label}
                onChange={(event) => setLabel(event.target.value)}
                maxLength={80}
                placeholder={`e.g. My ${selectedProvider?.label || "AI"} account`}
                disabled={Boolean(busy) || Boolean(pendingId)}
              />
            </label>
            <label>
              API key
              <input
                type="password"
                autoComplete="off"
                value={apiKey}
                onChange={(event) => setApiKey(event.target.value)}
                placeholder={
                  pendingId
                    ? "Saved securely; enter a replacement if needed"
                    : "Paste your provider API key here"
                }
                required={!pendingId}
                disabled={!canWrite || Boolean(busy)}
              />
            </label>
            <button
              type="button"
              className="workflow-secondary discover-models"
              disabled={
                !canWrite ||
                Boolean(busy) ||
                !apiKey.trim() ||
                (provider === "custom" && !baseUrl)
              }
              onClick={() =>
                void act("discover", async () => {
                  const result = await discoverProviderModels({
                    provider,
                    api_key: apiKey,
                    ...(provider === "custom" ? { base_url: baseUrl } : {}),
                  });
                  setModels(result.models);
                  if (
                    result.models.length &&
                    !result.models.includes(model) &&
                    !(
                      provider === "openrouter" &&
                      ["openrouter/free", "openrouter/auto"].includes(model)
                    )
                  )
                    setModel(result.models[0]);
                  setNotice(
                    `Loaded ${result.models.length} models. Select a text model below, then connect.`,
                  );
                })
              }
            >
              {busy === "discover"
                ? "Loading models…"
                : "Load available models"}
              <span>↓</span>
            </button>
            {provider === "openrouter" && models.length > 0 && (
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={freeOnly}
                  onChange={(event) => setFreeOnly(event.target.checked)}
                />
                Show free models only
              </label>
            )}
            <ModelPicker
              key={provider}
              label="Default model"
              models={choices}
              value={model}
              onChange={setModel}
              disabled={!canWrite || Boolean(busy)}
            />
            <div className="connect-form-action">
              <button
                className="workflow-primary"
                disabled={!canWrite || Boolean(busy) || !model.trim()}
              >
                {busy === "save"
                  ? "Connecting…"
                  : pendingId
                    ? "Retry saved connection"
                    : "Save and connect"}
              </button>
              <small>
                Your key stays on the backend. It is never returned to this
                browser.
              </small>
            </div>
          </form>
        </section>
        <section className="saved-connections-panel">
          <div className="panel-heading">
            <div>
              <small>READY FOR CHAT & AGENTS</small>
              <h3>
                Your connections{" "}
                <span>
                  {
                    connections.filter((item) => item.status === "active")
                      .length
                  }
                </span>
              </h3>
            </div>
          </div>
          {!connections.length && (
            <div className="connections-empty">
              <span>◈</span>
              <strong>Your AI team starts here</strong>
              <p>
                Paste a key on the left, load available models, then connect.
                You can add several providers and use a different model for
                every agent.
              </p>
              <div>
                <b>Chat</b>
                <b>Planning</b>
                <b>Coding</b>
                <b>Review</b>
              </div>
            </div>
          )}
          <div className="vault-connections">
            {connections.map((item) => (
              <SavedConnection
                key={`${item.id}:${item.default_model}`}
                item={item}
                disabled={!canWrite || Boolean(busy)}
                act={act}
                onConnected={onConnected}
              />
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}

function SavedConnection({
  item,
  disabled,
  act,
  onConnected,
}: {
  item: ProviderConnection;
  disabled: boolean;
  act: (key: string, action: () => Promise<void>) => Promise<void>;
  onConnected?: (connection: ProviderConnection) => void;
}) {
  const [model, setModel] = useState(item.default_model);
  const [replacement, setReplacement] = useState("");
  const [editKey, setEditKey] = useState(false);
  return (
    <article className={`saved-connection saved-${item.status}`}>
      <div className="vault-connection-heading">
        <span className={`vault-provider-icon provider-${item.provider}`}>
          {item.provider.slice(0, 2).toUpperCase()}
        </span>
        <div>
          <strong>{item.label}</strong>
          <small>
            {item.provider} · {item.masked_key}
          </small>
        </div>
        <span className={`connection-status connection-${item.status}`}>
          {item.status === "active"
            ? "Connected"
            : item.status === "invalid"
              ? "Needs attention"
              : item.status}
        </span>
      </div>
      <form
        className="workflow-form"
        onSubmit={(event) => {
          event.preventDefault();
          void act(`model-${item.id}`, async () => {
            if (model !== item.default_model)
              await updateProviderModel(item.id, model);
            if (replacement.trim()) {
              await updateProviderKey(item.id, replacement);
              setReplacement("");
            }
            const result = await testProviderConnection(item.id);
            setEditKey(false);
            onConnected?.(result.connection);
          });
        }}
      >
        <ModelPicker
          label={`Model for ${item.label}`}
          models={
            item.provider === "openrouter"
              ? [...(item.available_models || []), "openrouter/free"]
              : item.available_models || []
          }
          value={model}
          onChange={setModel}
          disabled={disabled}
        />
        {editKey && (
          <label>
            Replacement API key
            <input
              type="password"
              value={replacement}
              onChange={(event) => setReplacement(event.target.value)}
              autoComplete="off"
              disabled={disabled}
              placeholder="Paste the new key"
              required
            />
          </label>
        )}
        {item.last_test_message && (
          <small className="field-note">{item.last_test_message}</small>
        )}
        <div className="vault-connection-actions">
          <button className="workflow-secondary" disabled={disabled}>
            {model !== item.default_model || editKey
              ? "Save and test"
              : "Refresh models & test"}
          </button>
          <button
            type="button"
            className="workflow-text-button"
            disabled={disabled}
            onClick={() => {
              setEditKey(!editKey);
              setReplacement("");
            }}
          >
            {editKey ? "Cancel key change" : "Change API key"}
          </button>
        </div>
      </form>
      {item.status !== "disabled" && (
        <button
          className="connection-disconnect"
          type="button"
          disabled={disabled}
          onClick={() =>
            void act(`disable-${item.id}`, async () => {
              await disableProvider(item.id);
            })
          }
        >
          Disconnect
        </button>
      )}
    </article>
  );
}

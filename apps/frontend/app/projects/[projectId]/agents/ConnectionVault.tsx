"use client";

import { FormEvent, useState } from "react";
import {
  ProviderConnection,
  ProviderDefinition,
  addProviderConnection,
  discoverProviderModels,
  testProviderConnection,
  disableProvider,
  updateProviderModel,
} from "../../../../lib/orchestration";

export function ConnectionVault({
  catalog,
  connections,
  canWrite,
  onRefresh,
}: {
  catalog: ProviderDefinition[];
  connections: ProviderConnection[];
  canWrite: boolean;
  onRefresh: () => Promise<void>;
}) {
  const [provider, setProvider] = useState("openrouter"),
    [label, setLabel] = useState("");
  const [model, setModel] = useState("openrouter/free"),
    [apiKey, setApiKey] = useState(""),
    [baseUrl, setBaseUrl] = useState("");
  const [models, setModels] = useState<string[]>([]),
    [freeOnly, setFreeOnly] = useState(false);
  const [busy, setBusy] = useState(""),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
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
  }
  function submit(event: FormEvent) {
    event.preventDefault();
    void act("save", async () => {
      const saved = await addProviderConnection({
        provider,
        label:
          label.trim() ||
          `${catalog.find((item) => item.id === provider)?.label || provider} · ${model}`.slice(
            0,
            80,
          ),
        default_model: model,
        api_key: apiKey,
        ...(provider === "custom" ? { base_url: baseUrl } : {}),
      });
      setApiKey("");
      await onRefresh();
      const tested = await testProviderConnection(saved.id);
      await onRefresh();
      setNotice(
        `Connected ${saved.label}. ${tested.available_models.length} models are available for your nodes and chat.`,
      );
    });
  }
  const visibleModels = models.filter(
    (item) => !freeOnly || item.endsWith(":free") || item === "openrouter/free",
  );
  return (
    <div className="vault-layout">
      <section>
        <div className="inspector-section-label">ADD A CONNECTION</div>
        <p className="field-note">
          Your keys stay encrypted on the backend. One connection can power
          multiple models and workflow nodes.
        </p>
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
        <form className="workflow-form" onSubmit={submit}>
          <label>
            Provider
            <select
              value={provider}
              onChange={(event) => changeProvider(event.target.value)}
            >
              {catalog.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          {provider === "custom" && (
            <label>
              API base URL
              <input
                type="url"
                value={baseUrl}
                onChange={(event) => setBaseUrl(event.target.value)}
                placeholder="https://your-provider.com/v1"
                required
              />
              <span className="field-note">
                Use a public HTTPS endpoint supporting OpenAI chat completions.
              </span>
            </label>
          )}
          <label>
            Connection name
            <input
              value={label}
              onChange={(event) => setLabel(event.target.value)}
              maxLength={80}
              placeholder="e.g. My Gemini workspace"
            />
          </label>
          <label>
            API key
            <input
              type="password"
              autoComplete="off"
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              required
            />
          </label>
          <button
            type="button"
            className="workflow-secondary"
            disabled={
              !canWrite ||
              Boolean(busy) ||
              !apiKey ||
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
                if (!model && result.models.length) setModel(result.models[0]);
                setNotice(
                  `Loaded ${result.models.length} models. Choose a text model below.`,
                );
              })
            }
          >
            {busy === "discover" ? "Loading models…" : "Load available models"}
          </button>
          {provider === "openrouter" && models.length > 0 && (
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={freeOnly}
                onChange={(event) => setFreeOnly(event.target.checked)}
              />
              Show free models
            </label>
          )}
          <label>
            Default model
            <input
              list="vault-models"
              value={model}
              onChange={(event) => setModel(event.target.value)}
              placeholder="Choose or paste a model ID"
              required
            />
            <datalist id="vault-models">
              {visibleModels.map((item) => (
                <option key={item} value={item} />
              ))}
            </datalist>
            <span className="field-note">
              You can choose another model for each node after saving.
            </span>
          </label>
          <button
            className="workflow-primary"
            disabled={!canWrite || Boolean(busy)}
          >
            {busy === "save" ? "Saving and checking…" : "Save and connect"}
          </button>
        </form>
      </section>
      <section>
        <div className="inspector-section-label">
          YOUR CONNECTIONS · {connections.length}
        </div>
        {!connections.length && (
          <div className="inspector-empty">
            <strong>Connect your first model</strong>
            <p>
              Add a provider key, load its model catalog, then save. Your
              connections will appear here and in every node.
            </p>
          </div>
        )}
        <div className="vault-connections">
          {connections.map((item) => (
            <article key={item.id}>
              <div className="vault-connection-heading">
                <span
                  className={`vault-provider-icon provider-${item.provider}`}
                >
                  {item.provider.slice(0, 2).toUpperCase()}
                </span>
                <div>
                  <strong>{item.label}</strong>
                  <small>
                    {item.provider} · {item.masked_key}
                  </small>
                </div>
                <span className={`connection-status connection-${item.status}`}>
                  {item.status}
                </span>
              </div>
              <label className="workflow-form">
                Default model
                <input
                  key={item.default_model}
                  defaultValue={item.default_model}
                  list={`catalog-${item.id}`}
                  aria-label={`Model for ${item.label}`}
                  disabled={!canWrite || Boolean(busy)}
                  onBlur={(event) => {
                    if (
                      event.target.value.trim() &&
                      event.target.value.trim() !== item.default_model
                    )
                      void act(`model-${item.id}`, async () => {
                        await updateProviderModel(
                          item.id,
                          event.target.value.trim(),
                        );
                        await onRefresh();
                      });
                  }}
                />
                <datalist id={`catalog-${item.id}`}>
                  {item.available_models?.map((modelId) => (
                    <option key={modelId} value={modelId} />
                  ))}
                </datalist>
              </label>
              {item.last_test_message && (
                <small>{item.last_test_message}</small>
              )}
              <div className="vault-connection-actions">
                <button
                  className="workflow-secondary"
                  disabled={Boolean(busy)}
                  onClick={() =>
                    void act(`test-${item.id}`, async () => {
                      const tested = await testProviderConnection(item.id);
                      await onRefresh();
                      setNotice(
                        `${item.label}: ${tested.available_models.length} models loaded.`,
                      );
                    })
                  }
                >
                  {busy === `test-${item.id}`
                    ? "Checking…"
                    : "Refresh models & test"}
                </button>
                {item.status !== "disabled" && (
                  <button
                    className="workflow-text-danger"
                    disabled={!canWrite || Boolean(busy)}
                    onClick={() =>
                      void act(`disable-${item.id}`, async () => {
                        await disableProvider(item.id);
                        await onRefresh();
                      })
                    }
                  >
                    Disconnect
                  </button>
                )}
              </div>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}

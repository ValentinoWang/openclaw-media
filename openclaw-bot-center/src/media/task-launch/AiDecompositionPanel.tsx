import { AlertCircle, LoaderCircle, RotateCcw, Sparkles } from "lucide-react";
import type { CapabilityDefinition } from "../../schemas/capabilityCatalogSchema";
import type { TaskDraft } from "./taskDraft";
import { presentCapabilityText } from "./fieldPresentation";

export function AiDecompositionPanel({
  draft,
  capabilities,
  onQuery,
  onDecompose,
  onClear,
  onCandidate,
}: {
  draft: TaskDraft;
  capabilities: CapabilityDefinition[];
  onQuery: (value: string) => void;
  onDecompose: () => void;
  onClear: () => void;
  onCandidate: (capability: CapabilityDefinition, variantId: string) => void;
}) {
  const result = draft.matchResult;
  return (
    <section
      className="task-launch-section ai-decomposition"
      aria-labelledby="ai-decomposition-title"
      aria-busy={draft.phase === "decomposing"}
    >
      <div className="task-launch-section-heading">
        <span>1</span>
        <div>
          <h3 id="ai-decomposition-title">
            <Sparkles size={17} />
            AI 一键拆解
          </h3>
          <p>描述目标，AI 只推荐能力并预填字段。</p>
        </div>
        {draft.query ? (
          <button
            type="button"
            className="icon-button"
            title="清空拆解结果"
            aria-label="清空拆解结果"
            onClick={onClear}
          >
            <RotateCcw size={16} />
          </button>
        ) : null}
      </div>
      <textarea
        value={draft.query}
        onChange={(event) => onQuery(event.target.value)}
        rows={3}
        maxLength={4000}
        placeholder="例如：帮我把这个小红书博主录入达人库，主页链接是…"
      />
      <button
        type="button"
        className="ai-decompose-button"
        disabled={!draft.query.trim() || draft.phase === "decomposing"}
        onClick={onDecompose}
      >
        {draft.phase === "decomposing" ? (
          <LoaderCircle className="spin" size={16} />
        ) : (
          <Sparkles size={16} />
        )}
        {draft.phase === "decomposing" ? "正在拆解" : "AI 一键拆解"}
      </button>
      {result?.pathStatus === "matched" ? (
        <div className="ai-match-result">
          <strong>
            推荐：{pathFor(capabilities, result.steps[0]?.capabilityId)}
          </strong>
          <span>{presentCapabilityText(result.routeExplanation)}</span>
          {result.steps[0]?.issues.length ? (
            <ul>
              {result.steps[0].issues.map((issue) => (
                <li key={`${issue.code}-${issue.fieldKey}`}>
                  {presentCapabilityText(issue.message)}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
      {result?.pathStatus === "ambiguous" ? (
        <fieldset className="ai-candidates">
          <legend>你的需求可能对应</legend>
          {result.candidates.map((candidate, index) => {
            const capability = capabilities.find(
              (item) => item.capabilityId === candidate.capabilityId,
            );
            return capability ? (
              <label key={`${candidate.capabilityId}-${candidate.variantId}`}>
                <input
                  type="radio"
                  name="ai-candidate"
                  onChange={() => onCandidate(capability, candidate.variantId)}
                />
                <span>
                  {capability.hierarchy.pathNames
                    .map(presentCapabilityText)
                    .join(" / ")}
                </span>
                {index === 0 ? <b>推荐</b> : null}
                <small>{presentCapabilityText(candidate.reason)}</small>
              </label>
            ) : null;
          })}
        </fieldset>
      ) : null}
      {result?.pathStatus === "needs_clarification" ? (
        <div className="ai-clarification">
          <AlertCircle size={16} />
          <span>{presentCapabilityText(result.clarificationQuestion)}</span>
        </div>
      ) : null}
      {draft.error && draft.phase === "error" ? (
        <p className="form-error" role="alert">
          <AlertCircle size={15} />
          {draft.error}
        </p>
      ) : null}
    </section>
  );
}

function pathFor(capabilities: CapabilityDefinition[], capabilityId?: string) {
  return (
    capabilities
      .find((item) => item.capabilityId === capabilityId)
      ?.hierarchy.pathNames.map(presentCapabilityText)
      .join(" / ") ?? "待确认"
  );
}

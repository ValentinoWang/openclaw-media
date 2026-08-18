import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "../..");
const overviewPath = resolve(root, "src/media/pages/ordinary/OverviewPage.tsx");
const workspacePath = resolve(root, "src/media/MediaWebWorkspace.tsx");
const assetsPath = resolve(root, "src/media/pages/ordinary/AssetsPage.tsx");
const presentationPath = resolve(root, "src/media/recentTaskPresentation.ts");

function inspect(
  overview: string,
  workspace: string,
  assets: string,
  presentation: string,
): string[] {
  const failures: string[] = [];
  const requireContract = (condition: boolean, message: string) => {
    if (!condition) failures.push(message);
  };
  requireContract(
    overview.includes('data-confirmation-kind={presentation.kind}'),
    "Overview confirmation cards must expose their receipt kind",
  );
  requireContract(
    overview.includes('presentation.title') && overview.includes('presentation.impact'),
    "Overview must render confirmation-specific identity and impact",
  );
  requireContract(
      overview.includes('查看影响并确认') &&
      overview.includes('onClick={openTaskReview}') &&
      overview.includes('onOpenWorkspace();') &&
      overview.includes('`[data-task-id="${task.taskId}"]`') &&
      overview.includes('取消删除') &&
      overview.includes('isPendingTask(task, nowMs)') &&
      overview.includes('!Number.isFinite(expiresAt) || expiresAt <= nowMs') &&
      !overview.includes('重新生成删除预览') &&
      !overview.includes('useState("确认网页任务")'),
    "Overview must show only active review actions and exclude expired deletion confirmations",
  );
  requireContract(
    !overview.includes('"confirmMediaTask"'),
    "Overview must not approve tasks inline",
  );
  requireContract(
    overview.includes(
      "latestTaskFeed(tasks.filter((task) => !task.terminal))",
    ),
    "Overview current-task summary must hide deletion preview plumbing and expired confirmations",
  );
  requireContract(
    workspace.includes('className="task-confirmation-context is-destructive"'),
    "the task workspace must render destructive confirmation context",
  );
  requireContract(
    workspace.includes('data-task-id={task.taskId}') && workspace.includes('tabIndex={-1}'),
    "task review targets must expose a stable focus destination",
  );
  requireContract(
    workspace.includes('确认删除') && workspace.includes('删除影响'),
    "the task workspace must name the destructive action and its review surface",
  );
  requireContract(
    workspace.includes('latestTaskFeed(tasks, nowMs)') &&
      presentation.includes('if (task.variantId === "preview") return false;') &&
      presentation.includes('Number.isFinite(expiresAt) && expiresAt > nowMs'),
    "the user task feed must hide deletion preview plumbing and expired confirmations",
  );
  requireContract(
    assets.includes('prepareDeletionIntent') &&
      assets.includes('executeDeletionIntent') &&
      assets.includes('role="dialog"') &&
      assets.includes('删除素材') &&
      assets.includes('确认删除') &&
      !assets.includes('variantId: "preview"'),
    "asset deletion must stay on the Assets page and expose one user confirmation dialog",
  );
  return failures;
}

const overview = readFileSync(overviewPath, "utf8");
const workspace = readFileSync(workspacePath, "utf8");
const assets = readFileSync(assetsPath, "utf8");
const presentation = readFileSync(presentationPath, "utf8");
const failures = inspect(overview, workspace, assets, presentation);
if (failures.length > 0) {
  throw new Error(`Overview task confirmation contract failed:\n${failures.join("\n")}`);
}

if (process.env.OVERVIEW_CONFIRMATION_CONTRACT_SELF_TEST === "1") {
  const invalid = presentation.replace(
    'if (task.variantId === "preview") return false;',
    "",
  );
  if (inspect(overview, workspace, assets, invalid).length === 0) {
    throw new Error("Overview task confirmation contract negative fixture was not detected");
  }
  console.log("Overview task confirmation contract negative fixture passed.");
}

console.log("Overview task confirmation contract checks passed.");

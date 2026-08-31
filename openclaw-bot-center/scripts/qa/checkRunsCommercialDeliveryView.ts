import fs from "node:fs";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "../..");
const sourcePath = path.join(root, "src/media/pages/ordinary/RunsPage.tsx");

function requireGate(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

function validateCommercialDeliveryView(source: string): void {
  requireGate(
    /type View = "runs" \| "opportunities" \| "deliveries";/u.test(source),
    "commercial delivery view state is missing",
  );
  requireGate(
    /onClick=\{\(\) => switchView\("deliveries"\)\}/u.test(source),
    "commercial delivery tab is not interactive",
  );
  const labelOffset = source.indexOf("商单交付");
  const tabStart = source.lastIndexOf("<button", labelOffset);
  const tabEnd = source.indexOf("</button>", labelOffset);
  const tab = labelOffset >= 0 && tabStart >= 0 && tabEnd >= 0
    ? source.slice(tabStart, tabEnd + "</button>".length)
    : "";
  requireGate(tab.length > 0 && !/\bdisabled\b/u.test(tab), "commercial delivery tab regressed to a disabled placeholder");
  requireGate(
    /tasks\s*\}\s*= useMediaWeb\(\)/u.test(source) && /task\.capabilityId === "commercial_delivery_draft"/u.test(source),
    "commercial delivery tasks are not read from the live tenant task state",
  );
  requireGate(
    /openWorkspace\(\{\s*capabilityId:\s*"commercial_delivery_draft",\s*variantId:\s*"default"\s*\}\)/u.test(source),
    "new commercial delivery does not preselect the canonical capability",
  );
  requireGate(
    /task\.result\?\.links/u.test(source) && /target="_blank" rel="noreferrer"/u.test(source),
    "commercial delivery result links are not exposed safely",
  );
}

const source = fs.readFileSync(sourcePath, "utf8");

let disabledRegressionRejected = false;
try {
  validateCommercialDeliveryView(
    source.replace(
      'onClick={() => switchView("deliveries")}',
      "disabled",
    ),
  );
} catch (error) {
  disabledRegressionRejected = error instanceof Error && /not interactive|disabled placeholder/u.test(error.message);
}
requireGate(disabledRegressionRejected, "disabled-placeholder red fixture was accepted");

validateCommercialDeliveryView(source);
console.log("commercial delivery runs view gate passed");

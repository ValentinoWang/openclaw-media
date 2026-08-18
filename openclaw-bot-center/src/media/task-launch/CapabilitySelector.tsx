import { Check, ChevronDown, Search, Sparkles } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import type { CapabilityDefinition } from "../../schemas/capabilityCatalogSchema";
import type { MediaWebTask } from "../mediaWebApi";
import { presentCapabilityText } from "./fieldPresentation";

type CapabilityTreeNode = {
  key: string;
  name: string;
  order: number;
  children: Map<string, CapabilityTreeNode>;
  items: CapabilityDefinition[];
};

export function CapabilitySelector({
  capabilities,
  selectedId,
  aiRecommendedId,
  tasks,
  onSelect,
}: {
  capabilities: CapabilityDefinition[];
  selectedId: string;
  aiRecommendedId?: string;
  tasks: MediaWebTask[];
  onSelect: (capability: CapabilityDefinition) => void;
}) {
  const [query, setQuery] = useState("");
  const [openPaths, setOpenPaths] = useState<Set<string>>(() => new Set());
  const sectionRef = useRef<HTMLElement | null>(null);
  const recentIds = useMemo(
    () => [...new Set(tasks.map((task) => task.capabilityId))].slice(0, 4),
    [tasks],
  );
  const filtered = useMemo(() => {
    const normalized = normalizeSearch(query);
    return capabilities.filter(
      (item) =>
        !normalized ||
        normalizeSearch(
          [
            item.displayName,
            item.description,
            ...item.searchKeywords,
            ...item.hierarchy.pathNames,
          ].join(" "),
        ).includes(normalized),
    );
  }, [capabilities, query]);
  const roots = useMemo(() => buildCapabilityTree(filtered), [filtered]);

  function toggle(path: string) {
    setOpenPaths((current) => {
      if (current.has(path))
        return new Set(
          [...current].filter(
            (candidate) => candidate !== path && !candidate.startsWith(`${path}/`),
          ),
        );
      const parts = path.split("/");
      return new Set(parts.map((_, index) => parts.slice(0, index + 1).join("/")));
    });
  }

  function selectCapability(item: CapabilityDefinition) {
    const names = item.hierarchy.pathNames.filter(Boolean);
    const keys =
      item.hierarchy.pathIds.length === names.length
        ? item.hierarchy.pathIds
        : names;
    setOpenPaths(
      new Set(keys.map((_, index) => keys.slice(0, index + 1).join("/"))),
    );
    onSelect(item);
  }

  const recent = recentIds
    .map((id) => capabilities.find((item) => item.capabilityId === id))
    .filter((item): item is CapabilityDefinition => Boolean(item));
  return (
    <section
      ref={sectionRef}
      className="task-launch-section capability-selector"
      aria-labelledby="capability-selector-title"
    >
      <div className="task-launch-section-heading">
        <span>2</span>
        <div>
          <h3 id="capability-selector-title">选择能力</h3>
          <p>按业务路径查找，或直接搜索名称。</p>
        </div>
      </div>
      <label className="capability-search">
        <Search size={16} />
        <span className="sr-only">搜索能力</span>
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Escape") setQuery("");
            if (event.key === "ArrowDown") {
              event.preventDefault();
              sectionRef.current
                ?.querySelector<HTMLButtonElement>(
                  ".capability-option:not(:disabled)",
                )
                ?.focus();
            }
          }}
          placeholder="搜索能力或操作"
        />
      </label>
      {recent.length > 0 && !query ? (
        <div className="capability-shortcuts">
          <strong>最近使用</strong>
          {recent.map((item) => (
            <CapabilityButton
              key={item.capabilityId}
              item={item}
              depth={capabilityDepth(item)}
              selected={selectedId === item.capabilityId}
              recommended={aiRecommendedId === item.capabilityId}
              onSelect={selectCapability}
            />
          ))}
        </div>
      ) : null}
      <div className="capability-groups">
        {roots.map((root) => (
          <CapabilityTreeNodeView
            key={root.key}
            node={root}
            depth={0}
            query={query}
            openPaths={openPaths}
            selectedId={selectedId}
            aiRecommendedId={aiRecommendedId}
            parentPath=""
            onToggle={toggle}
            onSelect={selectCapability}
          />
        ))}
      </div>
      {!filtered.length ? (
        <p className="capability-empty">没有匹配的能力。</p>
      ) : null}
    </section>
  );
}

function buildCapabilityTree(capabilities: CapabilityDefinition[]) {
  const roots = new Map<string, CapabilityTreeNode>();
  for (const item of capabilities) {
    const names = item.hierarchy.pathNames.filter(Boolean);
    const ids =
      item.hierarchy.pathIds.length === names.length
        ? item.hierarchy.pathIds
        : names;
    let siblings = roots;
    for (let index = 0; index < names.length; index += 1) {
      const key = ids[index] ?? names[index];
      const node = siblings.get(key) ?? {
        key,
        name: names[index],
        order: hierarchyOrder(item, index),
        children: new Map<string, CapabilityTreeNode>(),
        items: [],
      };
      siblings.set(key, node);
      if (index === names.length - 1) node.items.push(item);
      siblings = node.children;
    }
  }
  return sortNodes(roots);
}

function hierarchyOrder(item: CapabilityDefinition, depth: number) {
  if (depth === 0) return item.hierarchy.categoryOrder;
  if (depth === 1) return item.hierarchy.objectOrder;
  return item.hierarchy.actionOrder;
}

function sortNodes(nodes: Map<string, CapabilityTreeNode>) {
  return [...nodes.values()].sort(
    (left, right) =>
      left.order - right.order || left.name.localeCompare(right.name, "zh-CN"),
  );
}

function descendantItems(node: CapabilityTreeNode): CapabilityDefinition[] {
  return [...node.items, ...sortNodes(node.children).flatMap(descendantItems)];
}

function nodeContainsSelection(node: CapabilityTreeNode, selectedId: string) {
  return descendantItems(node).some((item) => item.capabilityId === selectedId);
}

function CapabilityTreeNodeView({
  node,
  depth,
  query,
  openPaths,
  selectedId,
  aiRecommendedId,
  parentPath,
  onToggle,
  onSelect,
}: {
  node: CapabilityTreeNode;
  depth: number;
  query: string;
  openPaths: Set<string>;
  selectedId: string;
  aiRecommendedId?: string;
  parentPath: string;
  onToggle: (path: string) => void;
  onSelect: (item: CapabilityDefinition) => void;
}) {
  const children = sortNodes(node.children);
  const items = [...node.items].sort(
    (left, right) => left.displayOrder - right.displayOrder,
  );
  const allItems = descendantItems(node);
  const terminal = !children.length && items.length === 1;
  if (terminal)
    return (
      <CapabilityButton
        item={items[0]}
        depth={depth}
        selected={selectedId === items[0].capabilityId}
        recommended={aiRecommendedId === items[0].capabilityId}
        onSelect={onSelect}
      />
    );

  const path = parentPath ? `${parentPath}/${node.key}` : node.key;
  const open =
    query !== "" ||
    openPaths.has(path) ||
    nodeContainsSelection(node, selectedId);
  const isRoot = depth === 0;
  const content = open ? (
    <div
      className={isRoot ? "capability-subgroups" : "capability-node-children"}
    >
      {children.map((child) => (
        <CapabilityTreeNodeView
          key={child.key}
          node={child}
          depth={depth + 1}
          query={query}
          openPaths={openPaths}
          selectedId={selectedId}
          aiRecommendedId={aiRecommendedId}
          parentPath={path}
          onToggle={onToggle}
          onSelect={onSelect}
        />
      ))}
      {items.map((item) => (
        <CapabilityButton
          key={item.capabilityId}
          item={item}
          depth={depth}
          selected={selectedId === item.capabilityId}
          recommended={aiRecommendedId === item.capabilityId}
          onSelect={onSelect}
        />
      ))}
    </div>
  ) : null;

  return (
    <div
      className={isRoot ? "capability-group" : "capability-subgroup"}
      data-depth={Math.min(depth, 2)}
    >
      <button
        type="button"
        className={
          isRoot ? "capability-group-toggle" : "capability-object-toggle"
        }
        data-depth={Math.min(depth, 2)}
        aria-expanded={open}
        onClick={() => onToggle(path)}
      >
        <span>
          <strong>{presentCapabilityText(node.name)}</strong>
          <small>{nodeDescription(allItems.length)}</small>
        </span>
        <em>{allItems.length}</em>
        <ChevronDown size={isRoot ? 16 : 14} />
      </button>
      {content}
    </div>
  );
}

function nodeDescription(count: number) {
  return `包含 ${count} 项能力。`;
}

function capabilityDepth(item: CapabilityDefinition) {
  return Math.min(Math.max(item.hierarchy.pathNames.length - 1, 0), 2);
}

function CapabilityButton({
  item,
  depth = capabilityDepth(item),
  selected,
  recommended,
  onSelect,
}: {
  item: CapabilityDefinition;
  depth?: number;
  selected: boolean;
  recommended: boolean;
  onSelect: (item: CapabilityDefinition) => void;
}) {
  return (
    <button
      type="button"
      className={`capability-option ${selected ? "is-selected" : ""}`}
      data-capability-id={item.capabilityId}
      data-depth={Math.min(depth, 2)}
      disabled={!item.enabled}
      aria-pressed={selected}
      onClick={() => onSelect(item)}
    >
      <span>
        <strong>{presentCapabilityText(item.displayName)}</strong>
        <small>{presentCapabilityText(item.description)}</small>
      </span>
      {recommended ? (
        <b>
          <Sparkles size={13} />
          AI 推荐
        </b>
      ) : null}
      {selected ? <Check size={16} /> : null}
      {!item.enabled ? <em>规划中</em> : null}
    </button>
  );
}

function normalizeSearch(value: string) {
  return value
    .trim()
    .toLocaleLowerCase("zh-CN")
    .replace(/[\s\-_—>\/·]+/g, "");
}

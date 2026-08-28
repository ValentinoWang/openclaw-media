import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { createTranscriptionQueue } from "../transcription-queue.js";

const sourcePath = new URL("../transcription-queue.js", import.meta.url);
const forbiddenHostPaths = ["/Users/vsiyo", "/home/ubuntu"];

function portabilityViolations(source) {
  return forbiddenHostPaths.filter((path) => source.includes(path));
}

test("transcription queue accepts an explicit root and constructor fixture", () => {
  const configuredRoot = join(tmpdir(), "openclaw-queue-configured-root");
  const injectedRoot = join(tmpdir(), "openclaw-queue-fixture-root");
  const original = process.env.OPENCLAW_TRANSCRIPTION_QUEUE_ROOT;
  process.env.OPENCLAW_TRANSCRIPTION_QUEUE_ROOT = configuredRoot;
  try {
    assert.equal(createTranscriptionQueue().root, configuredRoot);
    assert.equal(createTranscriptionQueue({ dataRoot: injectedRoot }).root, join(injectedRoot, "transcription-queue"));
  } finally {
    if (original === undefined) delete process.env.OPENCLAW_TRANSCRIPTION_QUEUE_ROOT;
    else process.env.OPENCLAW_TRANSCRIPTION_QUEUE_ROOT = original;
  }
});

test("transcription queue static guard rejects personal and fixed host paths", () => {
  const source = readFileSync(sourcePath, "utf8");
  assert.deepEqual(portabilityViolations(source), []);
  assert.deepEqual(portabilityViolations('const path = "/Users/vsiyo/private";'), ["/Users/vsiyo"]);
  assert.deepEqual(portabilityViolations('const path = "/home/ubuntu/private";'), ["/home/ubuntu"]);
});

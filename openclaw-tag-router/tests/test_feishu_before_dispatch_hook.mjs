import assert from "node:assert/strict";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import {
  createFeishuTagRouterBeforeDispatchHandler,
  isMediaFeishuAccount,
  isDeepMathFeishuAccount,
  isTagRouterEntrypoint,
  resolveFeishuGlobalAdminContext,
} from "../index.js";
import tagRouterPlugin from "../index.js";
import { createTranscriptionQueue } from "../transcription-queue.js";
import { createTranscriptionJobQueue } from "../transcription-job-queue.js";

async function run() {
  assert.equal(isTagRouterEntrypoint("【说明】media"), true);
  assert.equal(isTagRouterEntrypoint("[message_id: om_test] 飞书用户： 【说明】media"), true);
  assert.equal(isTagRouterEntrypoint("请处理【codex】修复路由"), true);
  assert.equal(isTagRouterEntrypoint("普通聊天里提到【说明】入口"), false);
  assert.equal(isMediaFeishuAccount("feishu_media"), true);
  assert.equal(isMediaFeishuAccount("daily"), false);
  assert.equal(isDeepMathFeishuAccount("feishu_deepmath"), true);
  assert.deepEqual(
    resolveFeishuGlobalAdminContext(
      { globalAdminTenantId: "1", feishuGlobalAdminIds: "ou_admin,ou_second" },
      "ou_admin",
    ),
    {
      tenant_id: "1",
      operator_id: "ou_admin",
      is_maintainer: true,
      authorization: { principal: "feishu:ou_admin", is_maintainer: true },
    },
  );
  assert.deepEqual(
    resolveFeishuGlobalAdminContext(
      { globalAdminTenantId: "1", feishuGlobalAdminIds: "ou_admin,*" },
      "ou_unknown",
    ),
    {},
  );
  assert.deepEqual(
    resolveFeishuGlobalAdminContext(
      { globalAdminTenantId: "not-a-tenant", feishuGlobalAdminIds: "ou_admin" },
      "ou_admin",
    ),
    {},
  );

  const calls = [];
  const handler = createFeishuTagRouterBeforeDispatchHandler(
    { bridgeTimeoutMs: 1000 },
    {
      mediaExclusiveLabelsLoader: async () => new Set(["创作", "素材"]),
      bridgeRunner: async (config, mode, payload) => {
        calls.push({ config, mode, payload });
        return { ok: true, status: "capability_match", reply: "能力说明结果" };
      },
    },
  );

  const handled = await handler(
    {
      channel: "feishu",
      accountId: "daily",
      content: "【说明】帮我找创作入口",
      isGroup: false,
      messageId: "om_test",
      senderId: "ou_test",
    },
    {},
  );
  assert.deepEqual(handled, { handled: true, text: "能力说明结果" });
  assert.equal(calls.length, 1);

  const retiredCrossAccount = await handler(
    { channel: "feishu", accountId: "daily", content: "【创作】生成一条脚本" },
    {},
  );
  assert.equal(retiredCrossAccount.handled, true);
  assert.match(retiredCrossAccount.text, /MEDIA_FEISHU_COMMAND_RETIRED/);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].mode, "ingest");
  assert.equal(calls[0].payload.text, "【说明】帮我找创作入口");
  assert.equal(calls[0].payload.source, "feishu");
  assert.equal(calls[0].payload.chat_type, "private");
  assert.deepEqual(calls[0].payload.metadata, {
    account_id: "daily",
    source_message_id: "om_test",
    source_sender_id: "ou_test",
  });

  const xhsCalls = [];
  const xhsHandler = createFeishuTagRouterBeforeDispatchHandler(
    { bridgeTimeoutMs: 1000 },
    {
      mediaExclusiveLabelsLoader: async () => new Set(),
      bridgeRunner: async (_config, _mode, payload) => {
        xhsCalls.push(payload);
        return { ok: true, status: "selfmedia_knowledge_saved", reply: "自媒体知识已归档" };
      },
    },
  );
  const xhsShareText = "【自媒体知识】 🔥 如何用 Codex 生成高品位的UI界面 用 Codex 做 UI... http://xhslink.cn/o/2L1gituNZCn 保留这段，去【小红书】逛逛吧~";
  const xhsHandled = await xhsHandler(
    { channel: "feishu", accountId: "knowledge", content: xhsShareText, senderId: "ou_test" },
    {},
  );
  assert.deepEqual(xhsHandled, { handled: true, text: "自媒体知识已归档" });
  assert.equal(xhsCalls.length, 1);
  assert.equal(xhsCalls[0].text, xhsShareText);

  const adminCalls = [];
  const adminHandler = createFeishuTagRouterBeforeDispatchHandler(
    {
      bridgeTimeoutMs: 1000,
      globalAdminTenantId: "1",
      feishuGlobalAdminIds: "ou_admin",
    },
    {
      mediaExclusiveLabelsLoader: async () => new Set(),
      bridgeRunner: async (_config, _mode, payload) => {
        adminCalls.push(payload);
        return { ok: true, status: "creator_profile_listed", reply: "读取成功" };
      },
    },
  );
  await adminHandler(
    { channel: "feishu", accountId: "daily", content: "【博主】", senderId: "ou_admin" },
    {},
  );
  assert.deepEqual(adminCalls[0].metadata, {
    account_id: "daily",
    source_sender_id: "ou_admin",
    tenant_id: "1",
    operator_id: "ou_admin",
    is_maintainer: true,
    authorization: { principal: "feishu:ou_admin", is_maintainer: true },
  });

  assert.equal(await handler({ channel: "feishu", content: "普通聊天" }, {}), undefined);

  const deepmathCalls = [];
  const deepmathHandler = createFeishuTagRouterBeforeDispatchHandler(
    {},
    {
      mediaExclusiveLabelsLoader: async () => { throw new Error("DeepMath must bypass shared Media catalog"); },
      bridgeRunner: async (_config, _mode, payload) => {
        deepmathCalls.push(payload);
        return { ok: true, status: "deepmath_thinking_structured", reply: "已收件" };
      },
    },
  );
  const deepmathHandled = await deepmathHandler(
    {
      channel: "feishu", accountId: "deepmath", content: "【思考】验证一个假设", senderId: "ou_ceo", messageId: "om_deepmath",
      metadata: { mediaPaths: ["/tmp/evidence.png"], mediaTypes: ["image/png"], mediaNames: ["截图.png"] },
    },
    { conversationId: "oc_deepmath" },
  );
  assert.deepEqual(deepmathHandled, { handled: true, text: "已收件" });
  assert.equal(deepmathCalls.length, 1);
  assert.equal(deepmathCalls[0].metadata.account_id, "deepmath");
  assert.deepEqual(deepmathCalls[0].metadata.attachments, [{ local_path: "/tmp/evidence.png", mime_type: "image/png", file_name: "截图.png" }]);
  const deepmathGuide = await deepmathHandler(
    { channel: "feishu", accountId: "deepmath", content: "【说明】", senderId: "ou_ceo" },
    {},
  );
  assert.deepEqual(deepmathGuide, { handled: true, text: "已收件" });
  assert.equal(deepmathCalls.length, 2);
  assert.equal(deepmathCalls[1].text, "【说明】");
  assert.equal(Object.hasOwn(deepmathCalls[1].metadata, "attachments"), false);
  const blockedDeepmath = await deepmathHandler({ channel: "feishu", accountId: "deepmath", content: "【待办】直接建任务" }, {});
  assert.match(blockedDeepmath.text, /DEEPMATH_LABEL_BLOCKED/);
  assert.match(blockedDeepmath.text, /【思考】和【说明】/);
  assert.equal(blockedDeepmath.text.includes("仅开放【思考】持久化"), false);
  assert.equal(deepmathCalls.length, 2);
  const deepmathCodex = await deepmathHandler(
    { channel: "feishu", accountId: "deepmath", content: "【codex】修改 https://example.test/wiki/token", senderId: "ou_ceo" },
    {},
  );
  assert.deepEqual(deepmathCodex, { handled: true, text: "已收件" });
  assert.equal(deepmathCalls.length, 3);
  assert.equal(deepmathCalls[2].text.startsWith("【codex】"), true);
  assert.equal(deepmathCalls[2].metadata.account_id, "deepmath");
  const deepmathEmbeddedCodex = await deepmathHandler(
    { channel: "feishu", accountId: "deepmath", content: "请修改文档【codex】https://example.test/docx/token", senderId: "ou_ceo" },
    {},
  );
  assert.deepEqual(deepmathEmbeddedCodex, { handled: true, text: "已收件" });
  assert.equal(deepmathCalls.length, 4);

  const retiredTagged = await handler(
    { channel: "feishu", accountId: "media", content: "【创作】生成一条脚本" },
    {},
  );
  assert.equal(retiredTagged.handled, true);
  assert.match(retiredTagged.text, /MEDIA_FEISHU_COMMAND_RETIRED/);
  assert.match(retiredTagged.text, /http:\/\/106\.52\.146\.37\/openclaw\/media/);
  const retiredOrdinary = await handler(
    { channel: "feishu", accountId: "feishu-media", content: "帮我写一条小红书" },
    {},
  );
  assert.equal(retiredOrdinary.handled, true);
  assert.match(retiredOrdinary.text, /本条飞书消息未进入模型、tag-router 或附件队列/);
  assert.equal(calls.length, 1);

  const attachmentIntakeCalls = [];
  const attachmentIntakeHandler = createFeishuTagRouterBeforeDispatchHandler(
    {},
    {
      transcriptionQueue: {
        intake: (...args) => {
          attachmentIntakeCalls.push(args);
          return { text: "录音已暂存" };
        },
      },
    },
  );
  await attachmentIntakeHandler({ channel: "feishu", accountId: "media" }, { accountId: "media" });
  assert.equal(attachmentIntakeCalls.length, 0);
  const attachmentIntake = await attachmentIntakeHandler(
    { channel: "feishu", accountId: "daily" },
    { accountId: "daily" },
  );
  assert.deepEqual(attachmentIntake, { handled: true, text: "录音已暂存" });
  assert.equal(attachmentIntakeCalls.length, 1);

  const failingHandler = createFeishuTagRouterBeforeDispatchHandler(
    {},
    {
      mediaExclusiveLabelsLoader: async () => new Set(["创作"]),
      bridgeRunner: async () => { throw new Error("bridge offline"); },
    },
  );
  assert.deepEqual(
    await failingHandler({ channel: "feishu", content: "【说明】" }, {}),
    { handled: true, text: "[TAG_ROUTER_UNAVAILABLE] 标签入口暂时不可用。请稍后重试。" },
  );

  const timeoutHandler = createFeishuTagRouterBeforeDispatchHandler(
    {},
    {
      mediaExclusiveLabelsLoader: async () => new Set(),
      bridgeRunner: async () => {
        const error = new Error("bridge timed out");
        error.details = { timeout: true };
        throw error;
      },
    },
  );
  const timedOut = await timeoutHandler(
    { channel: "feishu", accountId: "knowledge", content: "【自媒体知识】https://xhslink.cn/o/example" },
    {},
  );
  assert.equal(timedOut.handled, true);
  assert.match(timedOut.text, /TAG_ROUTER_TIMEOUT/);
  assert.match(timedOut.text, /未继续写入/);

  const queueRoot = mkdtempSync(join(tmpdir(), "openclaw-transcription-queue-"));
  try {
    const firstAudio = join(queueRoot, "meeting-one---12345678-1234-1234-1234-123456789abc.m4a");
    const secondAudio = join(queueRoot, "meeting-two---12345678-1234-1234-1234-123456789abc.m4a");
    const thirdAudio = join(queueRoot, "meeting-three---12345678-1234-1234-1234-123456789abc.m4a");
    const fourthAudio = join(queueRoot, "meeting-four---12345678-1234-1234-1234-123456789abc.m4a");
    writeFileSync(firstAudio, "audio-one");
    writeFileSync(secondAudio, "audio-two");
    writeFileSync(thirdAudio, "audio-three");
    writeFileSync(fourthAudio, "audio-four");
    const routingQueue = createTranscriptionQueue({ dataRoot: queueRoot });
    const jobQueue = createTranscriptionJobQueue({ dataRoot: queueRoot });
    const transcriptionCalls = [];
    const transcriptionHandler = createFeishuTagRouterBeforeDispatchHandler(
      { dataRoot: queueRoot },
      {
        mediaExclusiveLabelsLoader: async () => new Set(["创作"]),
        transcriptionQueue: routingQueue,
        transcriptionJobQueue: jobQueue,
        bridgeRunner: async (config, mode, payload) => {
          transcriptionCalls.push({ config, mode, payload });
          return { ok: true, status: "archived", reply: "转写完成" };
        },
      },
    );
    const context = {
      channelId: "feishu",
      accountId: "daily",
      conversationId: "oc_daily_test",
      sessionKey: "agent:daily:feishu:test",
      senderId: "ou_daily_test",
    };
    const knowledgeContext = {
      channelId: "feishu",
      accountId: "knowledge",
      conversationId: "oc_knowledge_test",
      sessionKey: "agent:knowledge:feishu:test",
      senderId: "ou_knowledge_test",
    };
    const firstAutomatic = await transcriptionHandler(
      {
        channel: "feishu",
        accountId: "knowledge",
        from: "ou_knowledge_test",
        senderId: "ou_knowledge_test",
        messageId: "om_knowledge_audio_one",
        content: "<media:document> (知识会议一.m4a)",
        metadata: { mediaPaths: [firstAudio], mediaTypes: ["audio/x-m4a"] },
      },
      knowledgeContext,
    );
    const secondAutomatic = await transcriptionHandler(
      {
        channel: "feishu",
        accountId: "knowledge",
        from: "ou_knowledge_test",
        senderId: "ou_knowledge_test",
        messageId: "om_knowledge_audio_two",
        content: "<media:document> (知识会议二.m4a)",
        metadata: { mediaPaths: [secondAudio], mediaTypes: ["audio/x-m4a"] },
      },
      knowledgeContext,
    );
    assert.equal(firstAutomatic.handled, true);
    assert.equal(secondAutomatic.handled, true);
    assert.match(firstAutomatic.text, /转写任务已入队/);
    assert.match(secondAutomatic.text, /转写任务已入队/);
    const firstAutomaticJobId = firstAutomatic.text.match(/任务ID：(tr-[a-f0-9]+)/)?.[1];
    const secondAutomaticJobId = secondAutomatic.text.match(/任务ID：(tr-[a-f0-9]+)/)?.[1];
    assert.ok(firstAutomaticJobId);
    assert.ok(secondAutomaticJobId);
    assert.notEqual(firstAutomaticJobId, secondAutomaticJobId);
    const firstAutomaticJob = jobQueue.read(firstAutomaticJobId);
    const secondAutomaticJob = jobQueue.read(secondAutomaticJobId);
    assert.equal(firstAutomaticJob.source_message_id, "om_knowledge_audio_one");
    assert.equal(secondAutomaticJob.source_message_id, "om_knowledge_audio_two");
    assert.deepEqual(firstAutomaticJob.payload.metadata.downloaded_paths, [firstAudio]);
    assert.deepEqual(secondAutomaticJob.payload.metadata.downloaded_paths, [secondAudio]);
    assert.deepEqual(
      firstAutomaticJob.payload.metadata.transcription_attachments.map((item) => item.message_id),
      ["om_knowledge_audio_one"],
    );
    assert.deepEqual(
      secondAutomaticJob.payload.metadata.transcription_attachments.map((item) => item.message_id),
      ["om_knowledge_audio_two"],
    );
    assert.ok(firstAutomaticJob.enqueue_order < secondAutomaticJob.enqueue_order);
    assert.equal(transcriptionCalls.length, 0);

    const duplicateAutomatic = await transcriptionHandler(
      {
        channel: "feishu",
        accountId: "knowledge",
        from: "ou_knowledge_test",
        senderId: "ou_knowledge_test",
        messageId: "om_knowledge_audio_one",
        content: "<media:document> (知识会议一.m4a)",
        metadata: { mediaPaths: [firstAudio], mediaTypes: ["audio/x-m4a"] },
      },
      knowledgeContext,
    );
    assert.match(duplicateAutomatic.text, new RegExp(`任务ID：${firstAutomaticJobId}`));

    const firstIntake = await transcriptionHandler(
      {
        channel: "feishu",
        from: "ou_daily_test",
        senderId: "ou_daily_test",
        messageId: "om_audio_one",
        content: "<media:document> (多人讨论一.m4a)",
        metadata: { mediaPaths: [firstAudio], mediaTypes: ["audio/x-m4a"] },
      },
      context,
    );
    assert.equal(firstIntake.handled, true);
    assert.match(firstIntake.text, /录音已暂存/);
    assert.match(firstIntake.text, /多人讨论一\.m4a/);
    assert.equal(firstIntake.text.includes(firstAudio), false);
    assert.equal(transcriptionCalls.length, 0);

    const preview = await transcriptionHandler(
      {
        channel: "feishu",
        content: "【转写】请结合补充关键词整理",
        senderId: "ou_daily_test",
      },
      context,
    );
    assert.equal(preview.handled, true);
    assert.match(preview.text, /转写待确认/);
    assert.match(preview.text, /1\. 多人讨论一\.m4a/);
    assert.equal(preview.text.includes(firstAudio), false);
    assert.equal(transcriptionCalls.length, 0);
    const firstBatchId = preview.text.match(/批次：(tx-[a-f0-9]+)/)?.[1];
    assert.ok(firstBatchId);

    await transcriptionHandler(
      {
        channel: "feishu",
        from: "ou_daily_test",
        senderId: "ou_daily_test",
        messageId: "om_audio_two",
        content: "<media:document> (多人讨论二.m4a)",
        metadata: { mediaPaths: [secondAudio], mediaTypes: ["audio/x-m4a"] },
      },
      context,
    );
    await transcriptionHandler(
      {
        channel: "feishu",
        from: "ou_daily_test",
        senderId: "ou_daily_test",
        messageId: "om_audio_three",
        content: "<media:document> (多人讨论三.m4a)",
        metadata: { mediaPaths: [thirdAudio], mediaTypes: ["audio/x-m4a"] },
      },
      context,
    );
    const refreshed = await transcriptionHandler(
      {
        channel: "feishu",
        content: `【转写】确认 ${firstBatchId}`,
        senderId: "ou_daily_test",
      },
      context,
    );
    assert.match(refreshed.text, /转写批次已更新，请重新确认/);
    assert.match(refreshed.text, /多人讨论一\.m4a/);
    assert.match(refreshed.text, /多人讨论二\.m4a/);
    assert.match(refreshed.text, /多人讨论三\.m4a/);
    assert.equal(transcriptionCalls.length, 0);
    const refreshedBatchId = refreshed.text.match(/批次：(tx-[a-f0-9]+)/)?.[1];
    assert.ok(refreshedBatchId);
    assert.notEqual(refreshedBatchId, firstBatchId);

    const confirmed = await transcriptionHandler(
      {
        channel: "feishu",
        content: `【转写】确认 ${refreshedBatchId}`,
        senderId: "ou_daily_test",
      },
      context,
    );
    assert.equal(confirmed.handled, true);
    assert.match(confirmed.text, /转写任务已入队/);
    assert.match(confirmed.text, new RegExp(`任务ID：tr-${refreshedBatchId.slice(3)}`));
    assert.equal(transcriptionCalls.length, 0);
    const queuedJob = jobQueue.read(`tr-${refreshedBatchId.slice(3)}`);
    assert.ok(queuedJob);
    assert.equal(queuedJob.state, "queued");
    assert.equal(queuedJob.payload.text, "【转写】请结合补充关键词整理");
    assert.deepEqual(queuedJob.payload.metadata.downloaded_paths, [firstAudio, secondAudio, thirdAudio]);
    assert.equal(queuedJob.payload.metadata.transcription_batch_id, refreshedBatchId);
    assert.equal(queuedJob.payload.metadata.transcription_batch_confirmed, true);
    assert.deepEqual(
      queuedJob.payload.metadata.transcription_attachments.map((item) => item.name),
      ["多人讨论一.m4a", "多人讨论二.m4a", "多人讨论三.m4a"],
    );

    const duplicateConfirmation = await transcriptionHandler(
      {
        channel: "feishu",
        content: `【转写】确认 ${refreshedBatchId}`,
        senderId: "ou_daily_test",
      },
      context,
    );
    assert.match(duplicateConfirmation.text, new RegExp(`任务ID：tr-${refreshedBatchId.slice(3)}`));
    assert.equal(transcriptionCalls.length, 0);

    await transcriptionHandler(
      {
        channel: "feishu",
        from: "ou_daily_test",
        senderId: "ou_daily_test",
        messageId: "om_audio_four",
        content: "<media:document> (多人讨论四.m4a)",
        metadata: { mediaPaths: [fourthAudio], mediaTypes: ["audio/x-m4a"] },
      },
      context,
    );
    const cancellationPreview = await transcriptionHandler(
      { channel: "feishu", content: "【转写】", senderId: "ou_daily_test" },
      context,
    );
    const cancellationBatchId = cancellationPreview.text.match(/批次：(tx-[a-f0-9]+)/)?.[1];
    assert.ok(cancellationBatchId);
    const cancelled = await transcriptionHandler(
      {
        channel: "feishu",
        content: `【转写】取消 ${cancellationBatchId}`,
        senderId: "ou_daily_test",
      },
      context,
    );
    assert.match(cancelled.text, /已取消本批转写/);
    assert.match(cancelled.text, /多人讨论四\.m4a/);
    assert.equal(transcriptionCalls.length, 0);
  } finally {
    rmSync(queueRoot, { recursive: true, force: true });
  }

  const registeredHooks = [];
  tagRouterPlugin.register({
    runtime: {
      config: {
        loadConfig: () => ({
          plugins: { entries: { "openclaw-tag-router": { enabled: true, config: {} } } },
        }),
      },
    },
    logger: {},
    on: (...args) => registeredHooks.push(args),
    registerHttpRoute: () => {},
  });
  assert.equal(registeredHooks.length, 1);
  assert.equal(registeredHooks[0][0], "before_dispatch");
  assert.equal(typeof registeredHooks[0][1], "function");
  assert.deepEqual(registeredHooks[0][2], { priority: 1000 });
}

await run();
console.log("OK Feishu tag-router before-dispatch hook");

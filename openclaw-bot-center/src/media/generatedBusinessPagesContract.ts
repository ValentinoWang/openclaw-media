// Generated from accepted Media Web Business Pages IF2. Do not edit.
import { addAuditReasonHeader } from "./auditReasonHeader";

export const sourceSha256 = "97ccd7213e420cb0af8bcb43099eccd318587923874a1a4f2d177c89314fb548" as const;

export type OperationCategory = "page" | "shared" | "document";
export type GeneratedOperation = {
  readonly method: string;
  readonly path: string;
  readonly pathParameters: readonly string[];
  readonly queryParameters: readonly string[];
  readonly category: OperationCategory;
  readonly pageContracts: readonly string[];
  readonly permission: string;
  readonly runtimeStatus: string;
  readonly canonicalCapabilityIds: readonly string[];
  readonly existingHandlers: readonly string[];
  readonly productReadModels: readonly string[];
};

export const schemaNames = [
  "AccountMonitorResponse",
  "AccountMonitorUpdateRequest",
  "AccountTrackStrategyResponse",
  "AccountTrackStrategySummary",
  "AdminActionRequest",
  "AdminActionSummary",
  "AdminAdmissionBatch",
  "AdminAdmissionBatchListResponse",
  "AdminAdmissionBatchResponse",
  "AdminAffiliateUser",
  "AdminAffiliateUserListResponse",
  "AdminAffiliateUserResponse",
  "AdminBillingSummary",
  "AdminBillingSummaryResponse",
  "AdminCounts",
  "AdminDashboardResponse",
  "AdminOverview",
  "AdminPlatformCookieStatus",
  "AdminPlatformCookiesResponse",
  "AdminRegistrationPolicy",
  "AdminRegistrationPolicyResponse",
  "AdminTenantListResponse",
  "AdminTenantResponse",
  "AdminTenantSummary",
  "AdminUpstreamResponse",
  "AdminUpstreamSummary",
  "AffiliateProfile",
  "AffiliateProfileResponse",
  "ArtifactListResponse",
  "ArtifactResponse",
  "ArtifactSummary",
  "AssetDetail",
  "AssetListResponse",
  "AssetResponse",
  "AssetSummaryV2",
  "AuditSummary",
  "BalancePack",
  "BalancePackListResponse",
  "BillingBalance",
  "BillingBalanceResponse",
  "BillingPlan",
  "BillingUsageSummary",
  "BillingUsageSummaryResponse",
  "BusinessOpportunityListResponse",
  "BusinessOpportunitySummary",
  "CapabilityListResponse",
  "CapabilityMatch",
  "CapabilityMatchRequest",
  "CapabilityMatchResponse",
  "CapabilitySummary",
  "ConfirmDecisionRequest",
  "ConfirmReviewRequest",
  "ConfirmTaskRequest",
  "ContentProjectListResponse",
  "ContentProjectSummary",
  "CoverageSummary",
  "CreateAdminAdmissionBatchRequest",
  "CreateAdminBillingGrantRequest",
  "CreateAdminProductMappingRequest",
  "CreateAdminRedemptionBatchRequest",
  "CreateArtifactRevisionRequest",
  "CreateDocumentExportRequest",
  "CreateMediaTaskRequest",
  "CreateMetricImportRequest",
  "CreateProjectSummaryRequest",
  "CreatePublishedPostRequest",
  "CreateReviewRequest",
  "CreateUploadRequest",
  "CreatorListResponse",
  "CreatorResponse",
  "CreatorSummary",
  "DashboardCounts",
  "DashboardResponse",
  "DashboardSummary",
  "DecisionListResponse",
  "DecisionResponse",
  "DecisionSignal",
  "DecisionSignalListResponse",
  "DecisionSummary",
  "DisableAdminAdmissionBatchRequest",
  "DocumentArtifactKind",
  "DocumentArtifactRecord",
  "DocumentAttachmentBlock",
  "DocumentBlock",
  "DocumentBlockId",
  "DocumentBodyAuthority",
  "DocumentBodyRecord",
  "DocumentBodyResponse",
  "DocumentBodyV1",
  "DocumentCalloutBlock",
  "DocumentCodeBlock",
  "DocumentDataSnapshotBlock",
  "DocumentDividerBlock",
  "DocumentExportDownload",
  "DocumentExportDownloadResponse",
  "DocumentExportFormat",
  "DocumentExportRecord",
  "DocumentExportResponse",
  "DocumentExportState",
  "DocumentImageBlock",
  "DocumentInlineNode",
  "DocumentLinkMark",
  "DocumentListBlock",
  "DocumentListItem",
  "DocumentMark",
  "DocumentRevisionRecord",
  "DocumentRevisionResponse",
  "DocumentRevisionState",
  "DocumentRichTextBlock",
  "DocumentTableBlock",
  "DocumentTableCell",
  "DocumentTableRow",
  "DocumentTodoBlock",
  "DocxLink",
  "DocxLinkResponse",
  "ErrorDetail",
  "ErrorResponse",
  "EvidenceRef",
  "InviteeListResponse",
  "InviteeSummary",
  "MediaSession",
  "MediaSessionResponse",
  "MediaTask",
  "MediaTaskEvent",
  "MediaTaskEventListResponse",
  "MediaTaskListResponse",
  "MediaTaskResponse",
  "MetricListResponse",
  "MetricSnapshotDTO",
  "MutationReceipt",
  "NullableTimestamp",
  "OwnedAccountListResponse",
  "OwnedAccountResponse",
  "OwnedAccountSummary",
  "PublicId",
  "PublishedPostReceipt",
  "PublishedPostResponse",
  "PublishingPackage",
  "PublishingPackageListResponse",
  "PublishingPackageResponse",
  "RedeemBillingCodeRequest",
  "RedemptionBatchSummary",
  "ReviewAggregate",
  "ReviewListResponse",
  "ReviewSummary",
  "ReviewSummaryResponse",
  "Revision",
  "RevokeAdminUserSessionsRequest",
  "RunDecisionSection",
  "RunDecisionsResponse",
  "RunListResponse",
  "RunOutputSection",
  "RunOutputsResponse",
  "RunResponse",
  "RunSourceSection",
  "RunSourcesResponse",
  "RunSummary",
  "SaveDocumentDraftRequest",
  "SchemaVersion",
  "ServiceHealth",
  "StageCount",
  "StringList",
  "StringValueMap",
  "TaskResult",
  "TaskSummary",
  "Timestamp",
  "TrackListResponse",
  "TrackRelationship",
  "TrackRelationshipListResponse",
  "TrackResponse",
  "TrackSummary",
  "UpdateAdminAffiliateUserRequest",
  "UpdateAdminRegistrationPolicyRequest",
  "UpdatePublishingChecksRequest",
  "UploadReceipt",
  "UploadReceiptResponse",
  "UsageEvent",
  "UsageEventListResponse",
  "Value"
] as const;

export const schemaRefs = {
  "AccountMonitorResponse": "#/components/schemas/AccountMonitorResponse",
  "AccountMonitorUpdateRequest": "#/components/schemas/AccountMonitorUpdateRequest",
  "AccountTrackStrategyResponse": "#/components/schemas/AccountTrackStrategyResponse",
  "AccountTrackStrategySummary": "#/components/schemas/AccountTrackStrategySummary",
  "AdminActionRequest": "#/components/schemas/AdminActionRequest",
  "AdminActionSummary": "#/components/schemas/AdminActionSummary",
  "AdminAdmissionBatch": "#/components/schemas/AdminAdmissionBatch",
  "AdminAdmissionBatchListResponse": "#/components/schemas/AdminAdmissionBatchListResponse",
  "AdminAdmissionBatchResponse": "#/components/schemas/AdminAdmissionBatchResponse",
  "AdminAffiliateUser": "#/components/schemas/AdminAffiliateUser",
  "AdminAffiliateUserListResponse": "#/components/schemas/AdminAffiliateUserListResponse",
  "AdminAffiliateUserResponse": "#/components/schemas/AdminAffiliateUserResponse",
  "AdminBillingSummary": "#/components/schemas/AdminBillingSummary",
  "AdminBillingSummaryResponse": "#/components/schemas/AdminBillingSummaryResponse",
  "AdminCounts": "#/components/schemas/AdminCounts",
  "AdminDashboardResponse": "#/components/schemas/AdminDashboardResponse",
  "AdminOverview": "#/components/schemas/AdminOverview",
  "AdminPlatformCookieStatus": "#/components/schemas/AdminPlatformCookieStatus",
  "AdminPlatformCookiesResponse": "#/components/schemas/AdminPlatformCookiesResponse",
  "AdminRegistrationPolicy": "#/components/schemas/AdminRegistrationPolicy",
  "AdminRegistrationPolicyResponse": "#/components/schemas/AdminRegistrationPolicyResponse",
  "AdminTenantListResponse": "#/components/schemas/AdminTenantListResponse",
  "AdminTenantResponse": "#/components/schemas/AdminTenantResponse",
  "AdminTenantSummary": "#/components/schemas/AdminTenantSummary",
  "AdminUpstreamResponse": "#/components/schemas/AdminUpstreamResponse",
  "AdminUpstreamSummary": "#/components/schemas/AdminUpstreamSummary",
  "AffiliateProfile": "#/components/schemas/AffiliateProfile",
  "AffiliateProfileResponse": "#/components/schemas/AffiliateProfileResponse",
  "ArtifactListResponse": "#/components/schemas/ArtifactListResponse",
  "ArtifactResponse": "#/components/schemas/ArtifactResponse",
  "ArtifactSummary": "#/components/schemas/ArtifactSummary",
  "AssetDetail": "#/components/schemas/AssetDetail",
  "AssetListResponse": "#/components/schemas/AssetListResponse",
  "AssetResponse": "#/components/schemas/AssetResponse",
  "AssetSummaryV2": "#/components/schemas/AssetSummaryV2",
  "AuditSummary": "#/components/schemas/AuditSummary",
  "BalancePack": "#/components/schemas/BalancePack",
  "BalancePackListResponse": "#/components/schemas/BalancePackListResponse",
  "BillingBalance": "#/components/schemas/BillingBalance",
  "BillingBalanceResponse": "#/components/schemas/BillingBalanceResponse",
  "BillingPlan": "#/components/schemas/BillingPlan",
  "BillingUsageSummary": "#/components/schemas/BillingUsageSummary",
  "BillingUsageSummaryResponse": "#/components/schemas/BillingUsageSummaryResponse",
  "BusinessOpportunityListResponse": "#/components/schemas/BusinessOpportunityListResponse",
  "BusinessOpportunitySummary": "#/components/schemas/BusinessOpportunitySummary",
  "CapabilityListResponse": "#/components/schemas/CapabilityListResponse",
  "CapabilityMatch": "#/components/schemas/CapabilityMatch",
  "CapabilityMatchRequest": "#/components/schemas/CapabilityMatchRequest",
  "CapabilityMatchResponse": "#/components/schemas/CapabilityMatchResponse",
  "CapabilitySummary": "#/components/schemas/CapabilitySummary",
  "ConfirmDecisionRequest": "#/components/schemas/ConfirmDecisionRequest",
  "ConfirmReviewRequest": "#/components/schemas/ConfirmReviewRequest",
  "ConfirmTaskRequest": "#/components/schemas/ConfirmTaskRequest",
  "ContentProjectListResponse": "#/components/schemas/ContentProjectListResponse",
  "ContentProjectSummary": "#/components/schemas/ContentProjectSummary",
  "CoverageSummary": "#/components/schemas/CoverageSummary",
  "CreateAdminAdmissionBatchRequest": "#/components/schemas/CreateAdminAdmissionBatchRequest",
  "CreateAdminBillingGrantRequest": "#/components/schemas/CreateAdminBillingGrantRequest",
  "CreateAdminProductMappingRequest": "#/components/schemas/CreateAdminProductMappingRequest",
  "CreateAdminRedemptionBatchRequest": "#/components/schemas/CreateAdminRedemptionBatchRequest",
  "CreateArtifactRevisionRequest": "#/components/schemas/CreateArtifactRevisionRequest",
  "CreateDocumentExportRequest": "#/components/schemas/CreateDocumentExportRequest",
  "CreateMediaTaskRequest": "#/components/schemas/CreateMediaTaskRequest",
  "CreateMetricImportRequest": "#/components/schemas/CreateMetricImportRequest",
  "CreateProjectSummaryRequest": "#/components/schemas/CreateProjectSummaryRequest",
  "CreatePublishedPostRequest": "#/components/schemas/CreatePublishedPostRequest",
  "CreateReviewRequest": "#/components/schemas/CreateReviewRequest",
  "CreateUploadRequest": "#/components/schemas/CreateUploadRequest",
  "CreatorListResponse": "#/components/schemas/CreatorListResponse",
  "CreatorResponse": "#/components/schemas/CreatorResponse",
  "CreatorSummary": "#/components/schemas/CreatorSummary",
  "DashboardCounts": "#/components/schemas/DashboardCounts",
  "DashboardResponse": "#/components/schemas/DashboardResponse",
  "DashboardSummary": "#/components/schemas/DashboardSummary",
  "DecisionListResponse": "#/components/schemas/DecisionListResponse",
  "DecisionResponse": "#/components/schemas/DecisionResponse",
  "DecisionSignal": "#/components/schemas/DecisionSignal",
  "DecisionSignalListResponse": "#/components/schemas/DecisionSignalListResponse",
  "DecisionSummary": "#/components/schemas/DecisionSummary",
  "DisableAdminAdmissionBatchRequest": "#/components/schemas/DisableAdminAdmissionBatchRequest",
  "DocumentArtifactKind": "#/components/schemas/DocumentArtifactKind",
  "DocumentArtifactRecord": "#/components/schemas/DocumentArtifactRecord",
  "DocumentAttachmentBlock": "#/components/schemas/DocumentAttachmentBlock",
  "DocumentBlock": "#/components/schemas/DocumentBlock",
  "DocumentBlockId": "#/components/schemas/DocumentBlockId",
  "DocumentBodyAuthority": "#/components/schemas/DocumentBodyAuthority",
  "DocumentBodyRecord": "#/components/schemas/DocumentBodyRecord",
  "DocumentBodyResponse": "#/components/schemas/DocumentBodyResponse",
  "DocumentBodyV1": "#/components/schemas/DocumentBodyV1",
  "DocumentCalloutBlock": "#/components/schemas/DocumentCalloutBlock",
  "DocumentCodeBlock": "#/components/schemas/DocumentCodeBlock",
  "DocumentDataSnapshotBlock": "#/components/schemas/DocumentDataSnapshotBlock",
  "DocumentDividerBlock": "#/components/schemas/DocumentDividerBlock",
  "DocumentExportDownload": "#/components/schemas/DocumentExportDownload",
  "DocumentExportDownloadResponse": "#/components/schemas/DocumentExportDownloadResponse",
  "DocumentExportFormat": "#/components/schemas/DocumentExportFormat",
  "DocumentExportRecord": "#/components/schemas/DocumentExportRecord",
  "DocumentExportResponse": "#/components/schemas/DocumentExportResponse",
  "DocumentExportState": "#/components/schemas/DocumentExportState",
  "DocumentImageBlock": "#/components/schemas/DocumentImageBlock",
  "DocumentInlineNode": "#/components/schemas/DocumentInlineNode",
  "DocumentLinkMark": "#/components/schemas/DocumentLinkMark",
  "DocumentListBlock": "#/components/schemas/DocumentListBlock",
  "DocumentListItem": "#/components/schemas/DocumentListItem",
  "DocumentMark": "#/components/schemas/DocumentMark",
  "DocumentRevisionRecord": "#/components/schemas/DocumentRevisionRecord",
  "DocumentRevisionResponse": "#/components/schemas/DocumentRevisionResponse",
  "DocumentRevisionState": "#/components/schemas/DocumentRevisionState",
  "DocumentRichTextBlock": "#/components/schemas/DocumentRichTextBlock",
  "DocumentTableBlock": "#/components/schemas/DocumentTableBlock",
  "DocumentTableCell": "#/components/schemas/DocumentTableCell",
  "DocumentTableRow": "#/components/schemas/DocumentTableRow",
  "DocumentTodoBlock": "#/components/schemas/DocumentTodoBlock",
  "DocxLink": "#/components/schemas/DocxLink",
  "DocxLinkResponse": "#/components/schemas/DocxLinkResponse",
  "ErrorDetail": "#/components/schemas/ErrorDetail",
  "ErrorResponse": "#/components/schemas/ErrorResponse",
  "EvidenceRef": "#/components/schemas/EvidenceRef",
  "InviteeListResponse": "#/components/schemas/InviteeListResponse",
  "InviteeSummary": "#/components/schemas/InviteeSummary",
  "MediaSession": "#/components/schemas/MediaSession",
  "MediaSessionResponse": "#/components/schemas/MediaSessionResponse",
  "MediaTask": "#/components/schemas/MediaTask",
  "MediaTaskEvent": "#/components/schemas/MediaTaskEvent",
  "MediaTaskEventListResponse": "#/components/schemas/MediaTaskEventListResponse",
  "MediaTaskListResponse": "#/components/schemas/MediaTaskListResponse",
  "MediaTaskResponse": "#/components/schemas/MediaTaskResponse",
  "MetricListResponse": "#/components/schemas/MetricListResponse",
  "MetricSnapshotDTO": "#/components/schemas/MetricSnapshotDTO",
  "MutationReceipt": "#/components/schemas/MutationReceipt",
  "NullableTimestamp": "#/components/schemas/NullableTimestamp",
  "OwnedAccountListResponse": "#/components/schemas/OwnedAccountListResponse",
  "OwnedAccountResponse": "#/components/schemas/OwnedAccountResponse",
  "OwnedAccountSummary": "#/components/schemas/OwnedAccountSummary",
  "PublicId": "#/components/schemas/PublicId",
  "PublishedPostReceipt": "#/components/schemas/PublishedPostReceipt",
  "PublishedPostResponse": "#/components/schemas/PublishedPostResponse",
  "PublishingPackage": "#/components/schemas/PublishingPackage",
  "PublishingPackageListResponse": "#/components/schemas/PublishingPackageListResponse",
  "PublishingPackageResponse": "#/components/schemas/PublishingPackageResponse",
  "RedeemBillingCodeRequest": "#/components/schemas/RedeemBillingCodeRequest",
  "RedemptionBatchSummary": "#/components/schemas/RedemptionBatchSummary",
  "ReviewAggregate": "#/components/schemas/ReviewAggregate",
  "ReviewListResponse": "#/components/schemas/ReviewListResponse",
  "ReviewSummary": "#/components/schemas/ReviewSummary",
  "ReviewSummaryResponse": "#/components/schemas/ReviewSummaryResponse",
  "Revision": "#/components/schemas/Revision",
  "RevokeAdminUserSessionsRequest": "#/components/schemas/RevokeAdminUserSessionsRequest",
  "RunDecisionSection": "#/components/schemas/RunDecisionSection",
  "RunDecisionsResponse": "#/components/schemas/RunDecisionsResponse",
  "RunListResponse": "#/components/schemas/RunListResponse",
  "RunOutputSection": "#/components/schemas/RunOutputSection",
  "RunOutputsResponse": "#/components/schemas/RunOutputsResponse",
  "RunResponse": "#/components/schemas/RunResponse",
  "RunSourceSection": "#/components/schemas/RunSourceSection",
  "RunSourcesResponse": "#/components/schemas/RunSourcesResponse",
  "RunSummary": "#/components/schemas/RunSummary",
  "SaveDocumentDraftRequest": "#/components/schemas/SaveDocumentDraftRequest",
  "SchemaVersion": "#/components/schemas/SchemaVersion",
  "ServiceHealth": "#/components/schemas/ServiceHealth",
  "StageCount": "#/components/schemas/StageCount",
  "StringList": "#/components/schemas/StringList",
  "StringValueMap": "#/components/schemas/StringValueMap",
  "TaskResult": "#/components/schemas/TaskResult",
  "TaskSummary": "#/components/schemas/TaskSummary",
  "Timestamp": "#/components/schemas/Timestamp",
  "TrackListResponse": "#/components/schemas/TrackListResponse",
  "TrackRelationship": "#/components/schemas/TrackRelationship",
  "TrackRelationshipListResponse": "#/components/schemas/TrackRelationshipListResponse",
  "TrackResponse": "#/components/schemas/TrackResponse",
  "TrackSummary": "#/components/schemas/TrackSummary",
  "UpdateAdminAffiliateUserRequest": "#/components/schemas/UpdateAdminAffiliateUserRequest",
  "UpdateAdminRegistrationPolicyRequest": "#/components/schemas/UpdateAdminRegistrationPolicyRequest",
  "UpdatePublishingChecksRequest": "#/components/schemas/UpdatePublishingChecksRequest",
  "UploadReceipt": "#/components/schemas/UploadReceipt",
  "UploadReceiptResponse": "#/components/schemas/UploadReceiptResponse",
  "UsageEvent": "#/components/schemas/UsageEvent",
  "UsageEventListResponse": "#/components/schemas/UsageEventListResponse",
  "Value": "#/components/schemas/Value"
} as const;

export const operationIdsByPage = {
  "B01": [
    "createProjectSummary",
    "getDashboard",
    "getDocumentResource",
    "listContentProjects",
    "listProjectArtifacts"
  ],
  "B02": [
    "createMediaTask",
    "getAccountMonitor",
    "getAccountTrackStrategy",
    "getCreator",
    "getDocumentResource",
    "getOwnedAccount",
    "getTrack",
    "listCreators",
    "listOwnedAccounts",
    "listTrackRelationships",
    "listTracks",
    "pollAccountMonitor",
    "updateAccountMonitor",
    "updateTrackRelationshipStatus"
  ],
  "B03": [
    "createMediaTask",
    "getAsset",
    "getAssetPreview",
    "getDocumentResource",
    "listAssets"
  ],
  "B04": [
    "confirmDecision",
    "createMediaTask",
    "getDecision",
    "getDocumentResource",
    "listDecisionSignals",
    "listDecisions"
  ],
  "B05": [
    "createArtifactRevision",
    "createMediaTask",
    "getDocumentResource",
    "getRun",
    "getRunDecisions",
    "getRunOutputs",
    "getRunSources",
    "listBusinessOpportunities",
    "listRuns"
  ],
  "B06": [
    "createMediaTask",
    "createPublishedPost",
    "getDocumentResource",
    "getPublishedPost",
    "getPublishingPackage",
    "getResourceDocxLink",
    "listPublishingPackages",
    "updatePublishingChecks"
  ],
  "B07": [
    "confirmReview",
    "createMediaTask",
    "createMetricImport",
    "createReview",
    "getDocumentResource",
    "getReviewsSummary",
    "listAccountMetrics",
    "listContentMetrics",
    "listReviews"
  ],
  "B08": [
    "getBillingBalance",
    "getBillingUsageSummary",
    "listBillingBalancePacks",
    "listBillingUsage",
    "redeemBillingCode"
  ],
  "B09": [
    "getAffiliateProfile",
    "listInvitees"
  ],
  "B10": [
    "getAdminDashboard"
  ],
  "B11": [
    "createAdminAdmissionBatch",
    "disableAdminAdmissionBatch",
    "getAdminRegistrationPolicy",
    "listAdminAdmissionBatches",
    "listAdminAffiliateUsers",
    "revokeAdminUserSessions",
    "updateAdminAffiliateUser",
    "updateAdminRegistrationPolicy"
  ],
  "B12": [
    "getAdminTenant",
    "listAdminTenantRuns",
    "listAdminTenants"
  ],
  "B13": [
    "createAdminBillingGrant",
    "createAdminProductMapping",
    "createAdminRedemptionBatch",
    "getAdminBillingSummary",
    "recoverAdminFulfillment",
    "refundAdminFulfillment"
  ],
  "B14": [
    "getAdminPlatformCookies",
    "getAdminUpstreams",
    "reconcileAdminBillingOperation",
    "revokeAdminUpstreamCredential",
    "rotateAdminUpstreamCredential"
  ]
} as const;

export const pageOperationIds = [
  "confirmDecision",
  "confirmReview",
  "createAdminAdmissionBatch",
  "createAdminBillingGrant",
  "createAdminProductMapping",
  "createAdminRedemptionBatch",
  "createArtifactRevision",
  "createMediaTask",
  "createMetricImport",
  "createProjectSummary",
  "createPublishedPost",
  "createReview",
  "disableAdminAdmissionBatch",
  "getAccountTrackStrategy",
  "getAdminBillingSummary",
  "getAdminDashboard",
  "getAdminPlatformCookies",
  "getAdminRegistrationPolicy",
  "getAdminTenant",
  "getAdminUpstreams",
  "getAffiliateProfile",
  "getAsset",
  "getAssetPreview",
  "getBillingBalance",
  "getBillingUsageSummary",
  "getCreator",
  "getDashboard",
  "getDecision",
  "getOwnedAccount",
  "getPublishedPost",
  "getPublishingPackage",
  "getResourceDocxLink",
  "getReviewsSummary",
  "getRun",
  "getRunDecisions",
  "getRunOutputs",
  "getRunSources",
  "getTrack",
  "listAccountMetrics",
  "listAdminAdmissionBatches",
  "listAdminAffiliateUsers",
  "listAdminTenantRuns",
  "listAdminTenants",
  "listAssets",
  "listBillingBalancePacks",
  "listBillingUsage",
  "listBusinessOpportunities",
  "listContentMetrics",
  "listContentProjects",
  "listCreators",
  "listDecisionSignals",
  "listDecisions",
  "listInvitees",
  "listOwnedAccounts",
  "listProjectArtifacts",
  "listPublishingPackages",
  "listReviews",
  "listRuns",
  "listTrackRelationships",
  "listTracks",
  "reconcileAdminBillingOperation",
  "recoverAdminFulfillment",
  "redeemBillingCode",
  "refundAdminFulfillment",
  "revokeAdminUpstreamCredential",
  "revokeAdminUserSessions",
  "rotateAdminUpstreamCredential",
  "updateAdminAffiliateUser",
  "updateAdminRegistrationPolicy",
  "updatePublishingChecks",
  "updateTrackRelationshipStatus"
] as const;

export const sharedOperationIds = [
  "cancelMediaTask",
  "confirmMediaTask",
  "createMediaUpload",
  "getMediaSession",
  "getMediaTask",
  "listMediaCapabilities",
  "listMediaTaskEvents",
  "listMediaTasks",
  "matchMediaCapability"
] as const;

export const documentOperationIds = [
  "createDocumentExport",
  "getDocumentBody",
  "getDocumentExport",
  "getDocumentExportDownload",
  "getDocumentResource",
  "getDocumentRevision",
  "saveDocumentDraft"
] as const;

export const operationGroups = {
  page: pageOperationIds,
  shared: sharedOperationIds,
  document: documentOperationIds,
} as const;

export const operations = {
  "cancelMediaTask": {
    "canonicalCapabilityIds": [],
    "category": "shared",
    "existingHandlers": [],
    "method": "POST",
    "pageContracts": [
      "shared"
    ],
    "path": "/tasks/{taskId}/cancel",
    "pathParameters": [
      "taskId"
    ],
    "permission": "shared-session",
    "productReadModels": [],
    "queryParameters": [],
    "runtimeStatus": "existing_typed"
  },
  "confirmDecision": {
    "canonicalCapabilityIds": [
      "creation_decision_brief"
    ],
    "category": "page",
    "existingHandlers": [
      "handle_media_growth"
    ],
    "method": "POST",
    "pageContracts": [
      "B04"
    ],
    "path": "/decisions/{publicDecisionId}/confirm",
    "pathParameters": [
      "publicDecisionId"
    ],
    "permission": "ordinary-session",
    "productReadModels": [
      "decision_traces",
      "document_artifacts"
    ],
    "queryParameters": [],
    "runtimeStatus": "new"
  },
  "confirmMediaTask": {
    "canonicalCapabilityIds": [],
    "category": "shared",
    "existingHandlers": [],
    "method": "POST",
    "pageContracts": [
      "shared"
    ],
    "path": "/tasks/{taskId}/confirm",
    "pathParameters": [
      "taskId"
    ],
    "permission": "shared-session",
    "productReadModels": [],
    "queryParameters": [],
    "runtimeStatus": "existing_typed"
  },
  "confirmReview": {
    "canonicalCapabilityIds": [],
    "category": "page",
    "existingHandlers": [],
    "method": "POST",
    "pageContracts": [
      "B07"
    ],
    "path": "/reviews/{publicReviewId}/confirm",
    "pathParameters": [
      "publicReviewId"
    ],
    "permission": "ordinary-session",
    "productReadModels": [],
    "queryParameters": [],
    "runtimeStatus": "new"
  },
  "createAdminAdmissionBatch": {
    "canonicalCapabilityIds": [],
    "category": "page",
    "existingHandlers": [],
    "method": "POST",
    "pageContracts": [
      "B11"
    ],
    "path": "/admin/admission-batches",
    "pathParameters": [],
    "permission": "admin-session",
    "productReadModels": [],
    "queryParameters": [],
    "runtimeStatus": "existing_typed"
  },
  "createAdminBillingGrant": {
    "canonicalCapabilityIds": [],
    "category": "page",
    "existingHandlers": [],
    "method": "POST",
    "pageContracts": [
      "B13"
    ],
    "path": "/admin/billing/grants",
    "pathParameters": [],
    "permission": "admin-session",
    "productReadModels": [],
    "queryParameters": [],
    "runtimeStatus": "existing_typed"
  },
  "createAdminProductMapping": {
    "canonicalCapabilityIds": [],
    "category": "page",
    "existingHandlers": [],
    "method": "POST",
    "pageContracts": [
      "B13"
    ],
    "path": "/admin/billing/product-mappings",
    "pathParameters": [],
    "permission": "admin-session",
    "productReadModels": [],
    "queryParameters": [],
    "runtimeStatus": "existing_typed"
  },
  "createAdminRedemptionBatch": {
    "canonicalCapabilityIds": [],
    "category": "page",
    "existingHandlers": [],
    "method": "POST",
    "pageContracts": [
      "B13"
    ],
    "path": "/admin/billing/redemption-batches",
    "pathParameters": [],
    "permission": "admin-session",
    "productReadModels": [],
    "queryParameters": [],
    "runtimeStatus": "existing_typed"
  },
  "createArtifactRevision": {
    "canonicalCapabilityIds": [
      "document_edit"
    ],
    "category": "page",
    "existingHandlers": [
      "handle_修改"
    ],
    "method": "POST",
    "pageContracts": [
      "B05"
    ],
    "path": "/artifacts/{publicArtifactId}/revisions",
    "pathParameters": [
      "publicArtifactId"
    ],
    "permission": "ordinary-session",
    "productReadModels": [
      "document_artifacts",
      "document_revisions"
    ],
    "queryParameters": [],
    "runtimeStatus": "new"
  },
  "createDocumentExport": {
    "canonicalCapabilityIds": [],
    "category": "document",
    "existingHandlers": [],
    "method": "POST",
    "pageContracts": [
      "B01",
      "B02",
      "B03",
      "B04",
      "B05",
      "B06",
      "B07"
    ],
    "path": "/documents/{publicArtifactId}/exports",
    "pathParameters": [
      "publicArtifactId"
    ],
    "permission": "ordinary-session",
    "productReadModels": [],
    "queryParameters": [],
    "runtimeStatus": "new"
  },
  "createMediaTask": {
    "canonicalCapabilityIds": [
      "account_track_strategy",
      "activity_archive",
      "commercial_brief",
      "commercial_delivery_draft",
      "creation_checklist_lookup",
      "creation_decision_brief",
      "creator_profile_upsert",
      "external_research_brief",
      "id_business",
      "media_growth_review",
      "platform_hotlist",
      "post_review_signal",
      "publishing_pack_build",
      "selfmedia_cognition_accumulation",
      "selfmedia_creation",
      "selfmedia_creation_consultation",
      "selfmedia_data_review",
      "shooting_execution_plan",
      "source_asset_intake",
      "style_polish_run",
      "track_creator_membership_query",
      "track_registry_lookup",
      "viral_deconstruction",
      "vlog_inspiration_capture",
      "work_acceptance_report"
    ],
    "category": "page",
    "existingHandlers": [
      "handle_creation",
      "handle_generic.media_review",
      "handle_id_business",
      "handle_media_growth",
      "handle_media_growth_review",
      "handle_selfmedia_cognition",
      "handle_shooting_execution",
      "handle_style_polish",
      "handle_作品验收",
      "handle_创作咨询",
      "handle_创作检查",
      "handle_博主_入库",
      "handle_商单交付",
      "handle_拆解",
      "handle_数据复盘",
      "handle_活动",
      "handle_灵感_vlog",
      "handle_热榜"
    ],
    "method": "POST",
    "pageContracts": [
      "B02",
      "B03",
      "B04",
      "B05",
      "B06",
      "B07"
    ],
    "path": "/tasks",
    "pathParameters": [],
    "permission": "ordinary-session",
    "productReadModels": [
      "account_metric_snapshots",
      "account_track_strategies",
      "activities",
      "assets",
      "business_accounts",
      "business_opportunities",
      "creation_runs",
      "creative_patterns",
      "creator_profiles",
      "decision_traces",
      "document_artifacts",
      "document_revisions",
      "material_deconstructions",
      "metric_snapshots",
      "published_posts",
      "publishing_packages",
      "review_records",
      "signal_snapshots",
      "track_creator_memberships",
      "tracks"
    ],
    "queryParameters": [],
    "runtimeStatus": "existing_typed"
  },
  "createMediaUpload": {
    "canonicalCapabilityIds": [],
    "category": "shared",
    "existingHandlers": [],
    "method": "POST",
    "pageContracts": [
      "shared"
    ],
    "path": "/uploads",
    "pathParameters": [],
    "permission": "shared-session",
    "productReadModels": [],
    "queryParameters": [],
    "runtimeStatus": "existing_typed"
  },
  "createMetricImport": {
    "canonicalCapabilityIds": [
      "selfmedia_data_review"
    ],
    "category": "page",
    "existingHandlers": [
      "handle_数据复盘"
    ],
    "method": "POST",
    "pageContracts": [
      "B07"
    ],
    "path": "/metric-imports",
    "pathParameters": [],
    "permission": "ordinary-session",
    "productReadModels": [
      "metric_snapshots",
      "published_posts",
      "review_records"
    ],
    "queryParameters": [],
    "runtimeStatus": "new"
  },
  "createProjectSummary": {
    "canonicalCapabilityIds": [],
    "category": "page",
    "existingHandlers": [],
    "method": "POST",
    "pageContracts": [
      "B01"
    ],
    "path": "/content-projects/{publicProjectId}/summaries",
    "pathParameters": [
      "publicProjectId"
    ],
    "permission": "ordinary-session",
    "productReadModels": [],
    "queryParameters": [],
    "runtimeStatus": "new"
  },
  "createPublishedPost": {
    "canonicalCapabilityIds": [],
    "category": "page",
    "existingHandlers": [],
    "method": "POST",
    "pageContracts": [
      "B06"
    ],
    "path": "/published-posts",
    "pathParameters": [],
    "permission": "ordinary-session",
    "productReadModels": [],
    "queryParameters": [],
    "runtimeStatus": "new"
  },
  "createReview": {
    "canonicalCapabilityIds": [],
    "category": "page",
    "existingHandlers": [],
    "method": "POST",
    "pageContracts": [
      "B07"
    ],
    "path": "/reviews",
    "pathParameters": [],
    "permission": "ordinary-session",
    "productReadModels": [],
    "queryParameters": [],
    "runtimeStatus": "new"
  },
  "disableAdminAdmissionBatch": {
    "canonicalCapabilityIds": [],
    "category": "page",
    "existingHandlers": [],
    "method": "POST",
    "pageContracts": [
      "B11"
    ],
    "path": "/admin/admission-batches/{batchId}/disable",
    "pathParameters": [
      "batchId"
    ],
    "permission": "admin-session",
    "productReadModels": [],
    "queryParameters": [],
    "runtimeStatus": "existing_typed"
  },
  "getAccountTrackStrategy": {
    "canonicalCapabilityIds": [
      "account_track_strategy"
    ],
    "category": "page",
    "existingHandlers": [],
    "method": "GET",
    "pageContracts": [
      "B02"
    ],
    "path": "/owned-accounts/{publicAccountId}/track-strategy",
    "pathParameters": [
      "publicAccountId"
    ],
    "permission": "ordinary-session",
    "productReadModels": [
      "account_track_strategies"
    ],
    "queryParameters": [],
    "runtimeStatus": "new"
  },
  "getAdminBillingSummary": {
    "canonicalCapabilityIds": [],
    "category": "page",
    "existingHandlers": [],
    "method": "GET",
    "pageContracts": [
      "B13"
    ],
    "path": "/admin/billing/summary",
    "pathParameters": [],
    "permission": "admin-session",
    "productReadModels": [],
    "queryParameters": [],
    "runtimeStatus": "existing_typed"
  },
  "getAdminDashboard": {
    "canonicalCapabilityIds": [],
    "category": "page",
    "existingHandlers": [],
    "method": "GET",
    "pageContracts": [
      "B10"
    ],
    "path": "/admin/dashboard",
    "pathParameters": [],
    "permission": "admin-session",
    "productReadModels": [],
    "queryParameters": [],
    "runtimeStatus": "existing_extended"
  },
  "getAdminPlatformCookies": {
    "canonicalCapabilityIds": [],
    "category": "page",
    "existingHandlers": [],
    "method": "GET",
    "pageContracts": [
      "B14"
    ],
    "path": "/admin/platform-cookies",
    "pathParameters": [],
    "permission": "admin-session",
    "productReadModels": [],
    "queryParameters": [],
    "runtimeStatus": "new"
  },
  "getAdminRegistrationPolicy": {
    "canonicalCapabilityIds": [],
    "category": "page",
    "existingHandlers": [],
    "method": "GET",
    "pageContracts": [
      "B11"
    ],
    "path": "/admin/registration-policy",
    "pathParameters": [],
    "permission": "admin-session",
    "productReadModels": [],
    "queryParameters": [],
    "runtimeStatus": "existing_typed"
  },
  "getAdminTenant": {
    "canonicalCapabilityIds": [],
    "category": "page",
    "existingHandlers": [],
    "method": "GET",
    "pageContracts": [
      "B12"
    ],
    "path": "/admin/tenants/{publicTenantId}",
    "pathParameters": [
      "publicTenantId"
    ],
    "permission": "admin-cross-tenant-read",
    "productReadModels": [],
    "queryParameters": [],
    "runtimeStatus": "new"
  },
  "getAdminUpstreams": {
    "canonicalCapabilityIds": [],
    "category": "page",
    "existingHandlers": [],
    "method": "GET",
    "pageContracts": [
      "B14"
    ],
    "path": "/admin/upstreams",
    "pathParameters": [],
    "permission": "admin-session",
    "productReadModels": [],
    "queryParameters": [],
    "runtimeStatus": "new"
  },
  "getAffiliateProfile": {
    "canonicalCapabilityIds": [],
    "category": "page",
    "existingHandlers": [],
    "method": "GET",
    "pageContracts": [
      "B09"
    ],
    "path": "/account/affiliate",
    "pathParameters": [],
    "permission": "ordinary-session",
    "productReadModels": [],
    "queryParameters": [],
    "runtimeStatus": "existing_typed"
  },
  "getAsset": {
    "canonicalCapabilityIds": [
      "source_asset_intake",
      "viral_deconstruction"
    ],
    "category": "page",
    "existingHandlers": [
      "handle_media_growth",
      "handle_拆解"
    ],
    "method": "GET",
    "pageContracts": [
      "B03"
    ],
    "path": "/assets/{publicAssetId}",
    "pathParameters": [
      "publicAssetId"
    ],
    "permission": "ordinary-session",
    "productReadModels": [
      "assets",
      "creative_patterns",
      "material_deconstructions"
    ],
    "queryParameters": [],
    "runtimeStatus": "new"
  },
  "getAssetPreview": {
    "canonicalCapabilityIds": [
      "source_asset_intake"
    ],
    "category": "page",
    "existingHandlers": [
      "handle_media_growth"
    ],
    "method": "GET",
    "pageContracts": [
      "B03"
    ],
    "path": "/assets/{publicAssetId}/preview",
    "pathParameters": [
      "publicAssetId"
    ],
    "permission": "ordinary-session",
    "productReadModels": [
      "assets"
    ],
    "queryParameters": [],
    "runtimeStatus": "new"
  },
  "getBillingBalance": {
    "canonicalCapabilityIds": [],
    "category": "page",
    "existingHandlers": [],
    "method": "GET",
    "pageContracts": [
      "B08"
    ],
    "path": "/billing/balance",
    "pathParameters": [],
    "permission": "ordinary-session",
    "productReadModels": [],
    "queryParameters": [],
    "runtimeStatus": "existing_typed"
  },
  "getBillingUsageSummary": {
    "canonicalCapabilityIds": [],
    "category": "page",
    "existingHandlers": [],
    "method": "GET",
    "pageContracts": [
      "B08"
    ],
    "path": "/billing/usage-summary",
    "pathParameters": [],
    "permission": "ordinary-session",
    "productReadModels": [],
    "queryParameters": [],
    "runtimeStatus": "new"
  },
  "getCreator": {
    "canonicalCapabilityIds": [
      "creator_profile_lookup"
    ],
    "category": "page",
    "existingHandlers": [
      "handle_博主"
    ],
    "method": "GET",
    "pageContracts": [
      "B02"
    ],
    "path": "/creators/{publicCreatorId}",
    "pathParameters": [
      "publicCreatorId"
    ],
    "permission": "ordinary-session",
    "productReadModels": [
      "creator_profiles"
    ],
    "queryParameters": [],
    "runtimeStatus": "new"
  },
  "getDashboard": {
    "canonicalCapabilityIds": [],
    "category": "page",
    "existingHandlers": [],
    "method": "GET",
    "pageContracts": [
      "B01"
    ],
    "path": "/dashboard",
    "pathParameters": [],
    "permission": "ordinary-session",
    "productReadModels": [],
    "queryParameters": [],
    "runtimeStatus": "existing_extended"
  },
  "getDecision": {
    "canonicalCapabilityIds": [],
    "category": "page",
    "existingHandlers": [],
    "method": "GET",
    "pageContracts": [
      "B04"
    ],
    "path": "/decisions/{publicDecisionId}",
    "pathParameters": [
      "publicDecisionId"
    ],
    "permission": "ordinary-session",
    "productReadModels": [],
    "queryParameters": [],
    "runtimeStatus": "new"
  },
  "getDocumentBody": {
    "canonicalCapabilityIds": [],
    "category": "document",
    "existingHandlers": [],
    "method": "GET",
    "pageContracts": [
      "B01",
      "B02",
      "B03",
      "B04",
      "B05",
      "B06",
      "B07"
    ],
    "path": "/documents/{publicArtifactId}/body",
    "pathParameters": [
      "publicArtifactId"
    ],
    "permission": "ordinary-session",
    "productReadModels": [],
    "queryParameters": [],
    "runtimeStatus": "new"
  },
  "getDocumentExport": {
    "canonicalCapabilityIds": [],
    "category": "document",
    "existingHandlers": [],
    "method": "GET",
    "pageContracts": [
      "B01",
      "B02",
      "B03",
      "B04",
      "B05",
      "B06",
      "B07"
    ],
    "path": "/document-exports/{publicExportId}",
    "pathParameters": [
      "publicExportId"
    ],
    "permission": "ordinary-session",
    "productReadModels": [],
    "queryParameters": [],
    "runtimeStatus": "new"
  },
  "getDocumentExportDownload": {
    "canonicalCapabilityIds": [],
    "category": "document",
    "existingHandlers": [],
    "method": "GET",
    "pageContracts": [
      "B01",
      "B02",
      "B03",
      "B04",
      "B05",
      "B06",
      "B07"
    ],
    "path": "/document-exports/{publicExportId}/download",
    "pathParameters": [
      "publicExportId"
    ],
    "permission": "ordinary-session",
    "productReadModels": [],
    "queryParameters": [],
    "runtimeStatus": "new"
  },
  "getDocumentResource": {
    "canonicalCapabilityIds": [],
    "category": "document",
    "existingHandlers": [],
    "method": "GET",
    "pageContracts": [
      "B01",
      "B02",
      "B03",
      "B04",
      "B05",
      "B06",
      "B07"
    ],
    "path": "/document-resources/{publicResourceId}",
    "pathParameters": [
      "publicResourceId"
    ],
    "permission": "ordinary-session",
    "productReadModels": [],
    "queryParameters": [],
    "runtimeStatus": "new"
  },
  "getDocumentRevision": {
    "canonicalCapabilityIds": [],
    "category": "document",
    "existingHandlers": [],
    "method": "GET",
    "pageContracts": [
      "B01",
      "B02",
      "B03",
      "B04",
      "B05",
      "B06",
      "B07"
    ],
    "path": "/documents/{publicArtifactId}/revisions/{revision}",
    "pathParameters": [
      "publicArtifactId",
      "revision"
    ],
    "permission": "ordinary-session",
    "productReadModels": [],
    "queryParameters": [],
    "runtimeStatus": "new"
  },
  "getMediaSession": {
    "canonicalCapabilityIds": [],
    "category": "shared",
    "existingHandlers": [],
    "method": "GET",
    "pageContracts": [
      "shared"
    ],
    "path": "/session",
    "pathParameters": [],
    "permission": "shared-session",
    "productReadModels": [],
    "queryParameters": [],
    "runtimeStatus": "existing_typed"
  },
  "getMediaTask": {
    "canonicalCapabilityIds": [],
    "category": "shared",
    "existingHandlers": [],
    "method": "GET",
    "pageContracts": [
      "shared"
    ],
    "path": "/tasks/{taskId}",
    "pathParameters": [
      "taskId"
    ],
    "permission": "shared-session",
    "productReadModels": [],
    "queryParameters": [],
    "runtimeStatus": "existing_typed"
  },
  "getOwnedAccount": {
    "canonicalCapabilityIds": [
      "owned_media_account_lookup"
    ],
    "category": "page",
    "existingHandlers": [],
    "method": "GET",
    "pageContracts": [
      "B02"
    ],
    "path": "/owned-accounts/{publicAccountId}",
    "pathParameters": [
      "publicAccountId"
    ],
    "permission": "ordinary-session",
    "productReadModels": [
      "owned_media_accounts"
    ],
    "queryParameters": [],
    "runtimeStatus": "new"
  },
  "getAccountMonitor": {
    "canonicalCapabilityIds": [
      "account_monitor"
    ],
    "category": "page",
    "existingHandlers": [],
    "method": "GET",
    "pageContracts": [
      "B02"
    ],
    "path": "/owned-accounts/{publicAccountId}/monitor",
    "pathParameters": [
      "publicAccountId"
    ],
    "permission": "ordinary-session",
    "productReadModels": [
      "owned_media_accounts"
    ],
    "queryParameters": [],
    "runtimeStatus": "new"
  },
  "pollAccountMonitor": {
    "canonicalCapabilityIds": [
      "account_monitor"
    ],
    "category": "page",
    "existingHandlers": [],
    "method": "POST",
    "pageContracts": [
      "B02"
    ],
    "path": "/owned-accounts/{publicAccountId}/monitor/poll",
    "pathParameters": [
      "publicAccountId"
    ],
    "permission": "ordinary-session",
    "productReadModels": [
      "owned_media_accounts"
    ],
    "queryParameters": [],
    "runtimeStatus": "new"
  },
  "updateAccountMonitor": {
    "canonicalCapabilityIds": [
      "account_monitor"
    ],
    "category": "page",
    "existingHandlers": [],
    "method": "PUT",
    "pageContracts": [
      "B02"
    ],
    "path": "/owned-accounts/{publicAccountId}/monitor",
    "pathParameters": [
      "publicAccountId"
    ],
    "permission": "ordinary-session",
    "productReadModels": [
      "owned_media_accounts"
    ],
    "queryParameters": [],
    "runtimeStatus": "new"
  },
  "getPublishedPost": {
    "canonicalCapabilityIds": [],
    "category": "page",
    "existingHandlers": [],
    "method": "GET",
    "pageContracts": [
      "B06"
    ],
    "path": "/published-posts/{publicPostId}",
    "pathParameters": [
      "publicPostId"
    ],
    "permission": "ordinary-session",
    "productReadModels": [],
    "queryParameters": [],
    "runtimeStatus": "new"
  },
  "getPublishingPackage": {
    "canonicalCapabilityIds": [
      "creation_checklist_lookup",
      "media_growth_review",
      "work_acceptance_report"
    ],
    "category": "page",
    "existingHandlers": [
      "handle_media_growth",
      "handle_media_growth_review",
      "handle_作品验收",
      "handle_创作检查"
    ],
    "method": "GET",
    "pageContracts": [
      "B06"
    ],
    "path": "/publishing/packages/{publicPackageId}",
    "pathParameters": [
      "publicPackageId"
    ],
    "permission": "ordinary-session",
    "productReadModels": [
      "publishing_packages",
      "review_records"
    ],
    "queryParameters": [],
    "runtimeStatus": "new"
  },
  "getResourceDocxLink": {
    "canonicalCapabilityIds": [],
    "category": "page",
    "existingHandlers": [],
    "method": "GET",
    "pageContracts": [
      "B06"
    ],
    "path": "/resources/docx-link",
    "pathParameters": [],
    "permission": "ordinary-session",
    "productReadModels": [],
    "queryParameters": [
      "publicArtifactId"
    ],
    "runtimeStatus": "existing_extended"
  },
  "getReviewsSummary": {
    "canonicalCapabilityIds": [],
    "category": "page",
    "existingHandlers": [],
    "method": "GET",
    "pageContracts": [
      "B07"
    ],
    "path": "/reviews/summary",
    "pathParameters": [],
    "permission": "ordinary-session",
    "productReadModels": [],
    "queryParameters": [],
    "runtimeStatus": "new"
  },
  "getRun": {
    "canonicalCapabilityIds": [
      "selfmedia_creation",
      "shooting_execution_plan"
    ],
    "category": "page",
    "existingHandlers": [
      "handle_creation",
      "handle_media_growth",
      "handle_shooting_execution"
    ],
    "method": "GET",
    "pageContracts": [
      "B05"
    ],
    "path": "/runs/{publicRunId}",
    "pathParameters": [
      "publicRunId"
    ],
    "permission": "ordinary-session",
    "productReadModels": [
      "creation_runs",
      "document_artifacts"
    ],
    "queryParameters": [],
    "runtimeStatus": "existing_extended"
  },
  "getRunDecisions": {
    "canonicalCapabilityIds": [],
    "category": "page",
    "existingHandlers": [],
    "method": "GET",
    "pageContracts": [
      "B05"
    ],
    "path": "/runs/{publicRunId}/decisions",
    "pathParameters": [
      "publicRunId"
    ],
    "permission": "ordinary-session",
    "productReadModels": [],
    "queryParameters": [],
    "runtimeStatus": "existing_extended"
  },
  "getRunOutputs": {
    "canonicalCapabilityIds": [
      "style_polish_run"
    ],
    "category": "page",
    "existingHandlers": [
      "handle_style_polish"
    ],
    "method": "GET",
    "pageContracts": [
      "B05"
    ],
    "path": "/runs/{publicRunId}/outputs",
    "pathParameters": [
      "publicRunId"
    ],
    "permission": "ordinary-session",
    "productReadModels": [
      "creation_runs",
      "document_revisions"
    ],
    "queryParameters": [],
    "runtimeStatus": "existing_extended"
  },
  "getRunSources": {
    "canonicalCapabilityIds": [],
    "category": "page",
    "existingHandlers": [],
    "method": "GET",
    "pageContracts": [
      "B05"
    ],
    "path": "/runs/{publicRunId}/sources",
    "pathParameters": [
      "publicRunId"
    ],
    "permission": "ordinary-session",
    "productReadModels": [],
    "queryParameters": [],
    "runtimeStatus": "existing_extended"
  },
  "getTrack": {
    "canonicalCapabilityIds": [
      "track_registry_lookup"
    ],
    "category": "page",
    "existingHandlers": [
      "handle_media_growth"
    ],
    "method": "GET",
    "pageContracts": [
      "B02"
    ],
    "path": "/tracks/{publicTrackId}",
    "pathParameters": [
      "publicTrackId"
    ],
    "permission": "ordinary-session",
    "productReadModels": [
      "tracks"
    ],
    "queryParameters": [],
    "runtimeStatus": "new"
  },
  "listAccountMetrics": {
    "canonicalCapabilityIds": [],
    "category": "page",
    "existingHandlers": [],
    "method": "GET",
    "pageContracts": [
      "B07"
    ],
    "path": "/metrics/accounts",
    "pathParameters": [],
    "permission": "ordinary-session",
    "productReadModels": [],
    "queryParameters": [
      "cursor",
      "pageSize"
    ],
    "runtimeStatus": "new"
  },
  "listAdminAdmissionBatches": {
    "canonicalCapabilityIds": [],
    "category": "page",
    "existingHandlers": [],
    "method": "GET",
    "pageContracts": [
      "B11"
    ],
    "path": "/admin/admission-batches",
    "pathParameters": [],
    "permission": "admin-session",
    "productReadModels": [],
    "queryParameters": [
      "cursor",
      "pageSize"
    ],
    "runtimeStatus": "existing_typed"
  },
  "listAdminAffiliateUsers": {
    "canonicalCapabilityIds": [],
    "category": "page",
    "existingHandlers": [],
    "method": "GET",
    "pageContracts": [
      "B11"
    ],
    "path": "/admin/affiliate-users",
    "pathParameters": [],
    "permission": "admin-session",
    "productReadModels": [],
    "queryParameters": [
      "cursor",
      "pageSize",
      "search"
    ],
    "runtimeStatus": "existing_typed"
  },
  "listAdminTenantRuns": {
    "canonicalCapabilityIds": [],
    "category": "page",
    "existingHandlers": [],
    "method": "GET",
    "pageContracts": [
      "B12"
    ],
    "path": "/admin/tenants/{publicTenantId}/runs",
    "pathParameters": [
      "publicTenantId"
    ],
    "permission": "admin-cross-tenant-read",
    "productReadModels": [],
    "queryParameters": [
      "cursor",
      "pageSize"
    ],
    "runtimeStatus": "new"
  },
  "listAdminTenants": {
    "canonicalCapabilityIds": [],
    "category": "page",
    "existingHandlers": [],
    "method": "GET",
    "pageContracts": [
      "B12"
    ],
    "path": "/admin/tenants",
    "pathParameters": [],
    "permission": "admin-session",
    "productReadModels": [],
    "queryParameters": [
      "cursor",
      "pageSize",
      "search"
    ],
    "runtimeStatus": "new"
  },
  "listAssets": {
    "canonicalCapabilityIds": [
      "source_asset_intake",
      "vlog_inspiration_capture"
    ],
    "category": "page",
    "existingHandlers": [
      "handle_media_growth",
      "handle_灵感_vlog"
    ],
    "method": "GET",
    "pageContracts": [
      "B03"
    ],
    "path": "/assets",
    "pathParameters": [],
    "permission": "ordinary-session",
    "productReadModels": [
      "assets",
      "document_artifacts"
    ],
    "queryParameters": [
      "cursor",
      "pageSize",
      "search"
    ],
    "runtimeStatus": "existing_extended"
  },
  "listBillingBalancePacks": {
    "canonicalCapabilityIds": [],
    "category": "page",
    "existingHandlers": [],
    "method": "GET",
    "pageContracts": [
      "B08"
    ],
    "path": "/billing/balance-packs",
    "pathParameters": [],
    "permission": "ordinary-session",
    "productReadModels": [],
    "queryParameters": [],
    "runtimeStatus": "existing_typed"
  },
  "listBillingUsage": {
    "canonicalCapabilityIds": [],
    "category": "page",
    "existingHandlers": [],
    "method": "GET",
    "pageContracts": [
      "B08"
    ],
    "path": "/billing/usage",
    "pathParameters": [],
    "permission": "ordinary-session",
    "productReadModels": [],
    "queryParameters": [
      "cursor",
      "pageSize"
    ],
    "runtimeStatus": "existing_typed"
  },
  "listBusinessOpportunities": {
    "canonicalCapabilityIds": [
      "id_business"
    ],
    "category": "page",
    "existingHandlers": [
      "handle_id_business"
    ],
    "method": "GET",
    "pageContracts": [
      "B05"
    ],
    "path": "/business-opportunities",
    "pathParameters": [],
    "permission": "ordinary-session",
    "productReadModels": [
      "business_accounts",
      "business_opportunities"
    ],
    "queryParameters": [
      "cursor",
      "pageSize"
    ],
    "runtimeStatus": "new"
  },
  "listContentMetrics": {
    "canonicalCapabilityIds": [],
    "category": "page",
    "existingHandlers": [],
    "method": "GET",
    "pageContracts": [
      "B07"
    ],
    "path": "/metrics/content",
    "pathParameters": [],
    "permission": "ordinary-session",
    "productReadModels": [],
    "queryParameters": [
      "cursor",
      "pageSize"
    ],
    "runtimeStatus": "new"
  },
  "listContentProjects": {
    "canonicalCapabilityIds": [],
    "category": "page",
    "existingHandlers": [],
    "method": "GET",
    "pageContracts": [
      "B01"
    ],
    "path": "/content-projects",
    "pathParameters": [],
    "permission": "ordinary-session",
    "productReadModels": [],
    "queryParameters": [
      "cursor",
      "pageSize",
      "search"
    ],
    "runtimeStatus": "new"
  },
  "listCreators": {
    "canonicalCapabilityIds": [
      "creator_profile_lookup",
      "creator_profile_upsert"
    ],
    "category": "page",
    "existingHandlers": [
      "handle_博主",
      "handle_博主_入库"
    ],
    "method": "GET",
    "pageContracts": [
      "B02"
    ],
    "path": "/creators",
    "pathParameters": [],
    "permission": "ordinary-session",
    "productReadModels": [
      "account_metric_snapshots",
      "creator_profiles"
    ],
    "queryParameters": [
      "cursor",
      "pageSize",
      "search"
    ],
    "runtimeStatus": "new"
  },
  "listDecisionSignals": {
    "canonicalCapabilityIds": [
      "activity_archive",
      "platform_hotlist"
    ],
    "category": "page",
    "existingHandlers": [
      "handle_活动",
      "handle_热榜"
    ],
    "method": "GET",
    "pageContracts": [
      "B04"
    ],
    "path": "/decision-signals",
    "pathParameters": [],
    "permission": "ordinary-session",
    "productReadModels": [
      "activities",
      "signal_snapshots"
    ],
    "queryParameters": [
      "cursor",
      "pageSize"
    ],
    "runtimeStatus": "new"
  },
  "listDecisions": {
    "canonicalCapabilityIds": [
      "creation_decision_brief",
      "post_review_signal",
      "selfmedia_creation_consultation"
    ],
    "category": "page",
    "existingHandlers": [
      "handle_generic.media_review",
      "handle_media_growth",
      "handle_创作咨询"
    ],
    "method": "GET",
    "pageContracts": [
      "B04"
    ],
    "path": "/decisions",
    "pathParameters": [],
    "permission": "ordinary-session",
    "productReadModels": [
      "decision_traces",
      "document_artifacts",
      "review_records"
    ],
    "queryParameters": [
      "cursor",
      "pageSize",
      "search"
    ],
    "runtimeStatus": "new"
  },
  "listInvitees": {
    "canonicalCapabilityIds": [],
    "category": "page",
    "existingHandlers": [],
    "method": "GET",
    "pageContracts": [
      "B09"
    ],
    "path": "/account/invitees",
    "pathParameters": [],
    "permission": "ordinary-session",
    "productReadModels": [],
    "queryParameters": [
      "cursor",
      "pageSize"
    ],
    "runtimeStatus": "existing_typed"
  },
  "listMediaCapabilities": {
    "canonicalCapabilityIds": [],
    "category": "shared",
    "existingHandlers": [],
    "method": "GET",
    "pageContracts": [
      "shared"
    ],
    "path": "/capabilities",
    "pathParameters": [],
    "permission": "shared-session",
    "productReadModels": [],
    "queryParameters": [
      "cursor",
      "pageSize",
      "search"
    ],
    "runtimeStatus": "existing_typed"
  },
  "listMediaTaskEvents": {
    "canonicalCapabilityIds": [],
    "category": "shared",
    "existingHandlers": [],
    "method": "GET",
    "pageContracts": [
      "shared"
    ],
    "path": "/tasks/{taskId}/events",
    "pathParameters": [
      "taskId"
    ],
    "permission": "shared-session",
    "productReadModels": [],
    "queryParameters": [
      "cursor"
    ],
    "runtimeStatus": "existing_typed"
  },
  "listMediaTasks": {
    "canonicalCapabilityIds": [],
    "category": "shared",
    "existingHandlers": [],
    "method": "GET",
    "pageContracts": [
      "shared"
    ],
    "path": "/tasks",
    "pathParameters": [],
    "permission": "shared-session",
    "productReadModels": [],
    "queryParameters": [
      "cursor",
      "pageSize"
    ],
    "runtimeStatus": "existing_typed"
  },
  "listOwnedAccounts": {
    "canonicalCapabilityIds": [
      "owned_media_account_lookup"
    ],
    "category": "page",
    "existingHandlers": [],
    "method": "GET",
    "pageContracts": [
      "B02"
    ],
    "path": "/owned-accounts",
    "pathParameters": [],
    "permission": "ordinary-session",
    "productReadModels": [
      "owned_media_accounts"
    ],
    "queryParameters": [
      "cursor",
      "pageSize"
    ],
    "runtimeStatus": "new"
  },
  "listProjectArtifacts": {
    "canonicalCapabilityIds": [
      "commercial_brief",
      "commercial_delivery_draft",
      "external_research_brief",
      "selfmedia_cognition_accumulation"
    ],
    "category": "page",
    "existingHandlers": [
      "handle_media_growth",
      "handle_selfmedia_cognition",
      "handle_商单交付"
    ],
    "method": "GET",
    "pageContracts": [
      "B01"
    ],
    "path": "/content-projects/{publicProjectId}/artifacts",
    "pathParameters": [
      "publicProjectId"
    ],
    "permission": "ordinary-session",
    "productReadModels": [
      "business_opportunities",
      "document_artifacts",
      "document_revisions"
    ],
    "queryParameters": [
      "cursor",
      "pageSize"
    ],
    "runtimeStatus": "new"
  },
  "listPublishingPackages": {
    "canonicalCapabilityIds": [
      "publishing_pack_build"
    ],
    "category": "page",
    "existingHandlers": [
      "handle_media_growth"
    ],
    "method": "GET",
    "pageContracts": [
      "B06"
    ],
    "path": "/publishing/packages",
    "pathParameters": [],
    "permission": "ordinary-session",
    "productReadModels": [
      "document_revisions",
      "publishing_packages"
    ],
    "queryParameters": [
      "cursor",
      "pageSize"
    ],
    "runtimeStatus": "new"
  },
  "listReviews": {
    "canonicalCapabilityIds": [
      "media_growth_review",
      "post_review_signal",
      "selfmedia_data_review"
    ],
    "category": "page",
    "existingHandlers": [
      "handle_generic.media_review",
      "handle_media_growth_review",
      "handle_数据复盘"
    ],
    "method": "GET",
    "pageContracts": [
      "B07"
    ],
    "path": "/reviews",
    "pathParameters": [],
    "permission": "ordinary-session",
    "productReadModels": [
      "decision_traces",
      "metric_snapshots",
      "published_posts",
      "publishing_packages",
      "review_records"
    ],
    "queryParameters": [
      "cursor",
      "pageSize"
    ],
    "runtimeStatus": "new"
  },
  "listRuns": {
    "canonicalCapabilityIds": [
      "selfmedia_creation"
    ],
    "category": "page",
    "existingHandlers": [
      "handle_creation"
    ],
    "method": "GET",
    "pageContracts": [
      "B05"
    ],
    "path": "/runs",
    "pathParameters": [],
    "permission": "ordinary-session",
    "productReadModels": [
      "creation_runs",
      "document_artifacts"
    ],
    "queryParameters": [
      "cursor",
      "pageSize",
      "search"
    ],
    "runtimeStatus": "existing_extended"
  },
  "listTrackRelationships": {
    "canonicalCapabilityIds": [
      "track_creator_membership_query"
    ],
    "category": "page",
    "existingHandlers": [
      "handle_media_growth"
    ],
    "method": "GET",
    "pageContracts": [
      "B02"
    ],
    "path": "/track-relationships",
    "pathParameters": [],
    "permission": "ordinary-session",
    "productReadModels": [
      "track_creator_memberships"
    ],
    "queryParameters": [
      "cursor",
      "pageSize"
    ],
    "runtimeStatus": "new"
  },
  "listTracks": {
    "canonicalCapabilityIds": [
      "track_registry_lookup"
    ],
    "category": "page",
    "existingHandlers": [
      "handle_media_growth"
    ],
    "method": "GET",
    "pageContracts": [
      "B02"
    ],
    "path": "/tracks",
    "pathParameters": [],
    "permission": "ordinary-session",
    "productReadModels": [
      "tracks"
    ],
    "queryParameters": [
      "cursor",
      "pageSize",
      "search"
    ],
    "runtimeStatus": "new"
  },
  "matchMediaCapability": {
    "canonicalCapabilityIds": [],
    "category": "shared",
    "existingHandlers": [],
    "method": "POST",
    "pageContracts": [
      "shared"
    ],
    "path": "/capability-match",
    "pathParameters": [],
    "permission": "shared-session",
    "productReadModels": [],
    "queryParameters": [],
    "runtimeStatus": "existing_typed"
  },
  "reconcileAdminBillingOperation": {
    "canonicalCapabilityIds": [],
    "category": "page",
    "existingHandlers": [],
    "method": "POST",
    "pageContracts": [
      "B14"
    ],
    "path": "/admin/billing/reconciliation/{operationId}",
    "pathParameters": [
      "operationId"
    ],
    "permission": "admin-session",
    "productReadModels": [],
    "queryParameters": [],
    "runtimeStatus": "existing_typed"
  },
  "recoverAdminFulfillment": {
    "canonicalCapabilityIds": [],
    "category": "page",
    "existingHandlers": [],
    "method": "POST",
    "pageContracts": [
      "B13"
    ],
    "path": "/admin/billing/fulfillments/{fulfillmentId}/recover",
    "pathParameters": [
      "fulfillmentId"
    ],
    "permission": "admin-session",
    "productReadModels": [],
    "queryParameters": [],
    "runtimeStatus": "existing_typed"
  },
  "redeemBillingCode": {
    "canonicalCapabilityIds": [],
    "category": "page",
    "existingHandlers": [],
    "method": "POST",
    "pageContracts": [
      "B08"
    ],
    "path": "/billing/redeem",
    "pathParameters": [],
    "permission": "ordinary-session",
    "productReadModels": [],
    "queryParameters": [],
    "runtimeStatus": "existing_typed"
  },
  "refundAdminFulfillment": {
    "canonicalCapabilityIds": [],
    "category": "page",
    "existingHandlers": [],
    "method": "POST",
    "pageContracts": [
      "B13"
    ],
    "path": "/admin/billing/fulfillments/{fulfillmentId}/refund",
    "pathParameters": [
      "fulfillmentId"
    ],
    "permission": "admin-session",
    "productReadModels": [],
    "queryParameters": [],
    "runtimeStatus": "existing_typed"
  },
  "revokeAdminUpstreamCredential": {
    "canonicalCapabilityIds": [],
    "category": "page",
    "existingHandlers": [],
    "method": "POST",
    "pageContracts": [
      "B14"
    ],
    "path": "/admin/upstream-credential/revoke",
    "pathParameters": [],
    "permission": "admin-maintainer",
    "productReadModels": [],
    "queryParameters": [],
    "runtimeStatus": "existing_typed"
  },
  "revokeAdminUserSessions": {
    "canonicalCapabilityIds": [],
    "category": "page",
    "existingHandlers": [],
    "method": "POST",
    "pageContracts": [
      "B11"
    ],
    "path": "/admin/users/{userId}/sessions/revoke-all",
    "pathParameters": [
      "userId"
    ],
    "permission": "admin-session",
    "productReadModels": [],
    "queryParameters": [],
    "runtimeStatus": "existing_typed"
  },
  "rotateAdminUpstreamCredential": {
    "canonicalCapabilityIds": [],
    "category": "page",
    "existingHandlers": [],
    "method": "POST",
    "pageContracts": [
      "B14"
    ],
    "path": "/admin/upstream-credential/rotate",
    "pathParameters": [],
    "permission": "admin-maintainer",
    "productReadModels": [],
    "queryParameters": [],
    "runtimeStatus": "existing_typed"
  },
  "saveDocumentDraft": {
    "canonicalCapabilityIds": [],
    "category": "document",
    "existingHandlers": [],
    "method": "PUT",
    "pageContracts": [
      "B01",
      "B02",
      "B03",
      "B04",
      "B05",
      "B06",
      "B07"
    ],
    "path": "/documents/{publicArtifactId}/draft",
    "pathParameters": [
      "publicArtifactId"
    ],
    "permission": "ordinary-session",
    "productReadModels": [],
    "queryParameters": [],
    "runtimeStatus": "new"
  },
  "updateAdminAffiliateUser": {
    "canonicalCapabilityIds": [],
    "category": "page",
    "existingHandlers": [],
    "method": "PUT",
    "pageContracts": [
      "B11"
    ],
    "path": "/admin/affiliate-users/{userId}",
    "pathParameters": [
      "userId"
    ],
    "permission": "admin-session",
    "productReadModels": [],
    "queryParameters": [],
    "runtimeStatus": "existing_typed"
  },
  "updateAdminRegistrationPolicy": {
    "canonicalCapabilityIds": [],
    "category": "page",
    "existingHandlers": [],
    "method": "PUT",
    "pageContracts": [
      "B11"
    ],
    "path": "/admin/registration-policy",
    "pathParameters": [],
    "permission": "admin-session",
    "productReadModels": [],
    "queryParameters": [],
    "runtimeStatus": "existing_typed"
  },
  "updatePublishingChecks": {
    "canonicalCapabilityIds": [],
    "category": "page",
    "existingHandlers": [],
    "method": "PUT",
    "pageContracts": [
      "B06"
    ],
    "path": "/publishing/packages/{publicPackageId}/checks",
    "pathParameters": [
      "publicPackageId"
    ],
    "permission": "ordinary-session",
    "productReadModels": [],
    "queryParameters": [],
    "runtimeStatus": "new"
  },
  "updateTrackRelationshipStatus": {
    "canonicalCapabilityIds": [
      "track_creator_membership_query"
    ],
    "category": "page",
    "existingHandlers": [
      "handle_media_growth"
    ],
    "method": "PUT",
    "pageContracts": [
      "B02"
    ],
    "path": "/track-relationships/{publicRelationshipId}",
    "pathParameters": [
      "publicRelationshipId"
    ],
    "permission": "ordinary-session",
    "productReadModels": [
      "track_creator_memberships"
    ],
    "queryParameters": [],
    "runtimeStatus": "new"
  }
} as const satisfies Record<string, GeneratedOperation>;

export type SchemaName = (typeof schemaNames)[number];
export type SchemaRef = (typeof schemaRefs)[SchemaName];
export type PageId = keyof typeof operationIdsByPage;
export type PageOperationId = (typeof pageOperationIds)[number];
export type SharedOperationId = (typeof sharedOperationIds)[number];
export type DocumentOperationId = (typeof documentOperationIds)[number];
export type OperationId = keyof typeof operations;

export type BusinessOperationRequest = {
  readonly path?: Readonly<Record<string, unknown>>;
  readonly query?: Readonly<Record<string, unknown>>;
  readonly body?: unknown;
  readonly signal?: AbortSignal;
  readonly csrfToken?: string;
  readonly idempotencyKey?: string;
  readonly auditReason?: string;
};

export class BusinessOperationError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(
    status: number,
    code: string,
    message: string,
  ) {
    super(message);
    this.name = "BusinessOperationError";
    this.status = status;
    this.code = code;
  }
}

function appendQueryValue(search: URLSearchParams, name: string, value: unknown): void {
  if (value === undefined || value === null) return;
  if (Array.isArray(value)) {
    for (const item of value) appendQueryValue(search, name, item);
    return;
  }
  search.append(name, String(value));
}

export async function callBusinessOperation<T>(
  operationId: OperationId,
  request: BusinessOperationRequest = {},
): Promise<T> {
  const operation = (operations as Record<string, GeneratedOperation>)[operationId];
  if (!operation) {
    throw new BusinessOperationError(0, "undeclared_operation", `Undeclared operation: ${operationId}`);
  }

  const suppliedPath = request.path ?? {};
  const unexpectedPath = Object.keys(suppliedPath).filter(
    (name) => !operation.pathParameters.includes(name),
  );
  if (unexpectedPath.length > 0) {
    throw new BusinessOperationError(0, "unexpected_path_parameter", `Unexpected path parameter: ${unexpectedPath[0]}`);
  }
  let expandedPath = operation.path;
  for (const name of operation.pathParameters) {
    const value = suppliedPath[name];
    if (value === undefined || value === null || value === "") {
      throw new BusinessOperationError(0, "missing_path_parameter", `Missing path parameter: ${name}`);
    }
    expandedPath = expandedPath.replace(`{${name}}`, encodeURIComponent(String(value)));
  }

  const search = new URLSearchParams();
  const suppliedQuery = request.query ?? {};
  for (const name of operation.queryParameters) {
    appendQueryValue(search, name, suppliedQuery[name]);
  }
  const queryString = search.toString();
  const url = `/openclaw/media/api${expandedPath}${queryString ? `?${queryString}` : ""}`;
  const headers: Record<string, string> = { Accept: "application/json" };
  if (request.body !== undefined) headers["Content-Type"] = "application/json";
  if (request.csrfToken) headers["X-OpenClaw-CSRF"] = request.csrfToken;
  if (request.idempotencyKey) headers["Idempotency-Key"] = request.idempotencyKey;
  if (request.auditReason) addAuditReasonHeader(headers, request.auditReason);

  const response = await fetch(url, {
    method: operation.method,
    credentials: "same-origin",
    headers,
    body: request.body === undefined ? undefined : JSON.stringify(request.body),
    signal: request.signal,
  });
  const payload = response.status === 204 ? undefined : await response.json().catch(() => undefined);
  if (!response.ok) {
    const detail = payload && typeof payload === "object" && "error" in payload
      ? (payload as { error?: { code?: unknown; message?: unknown } }).error
      : undefined;
    const code = typeof detail?.code === "string" ? detail.code : `http_${response.status}`;
    const message = typeof detail?.message === "string" ? detail.message : response.statusText || "Request failed";
    throw new BusinessOperationError(response.status, code, message);
  }
  return payload as T;
}

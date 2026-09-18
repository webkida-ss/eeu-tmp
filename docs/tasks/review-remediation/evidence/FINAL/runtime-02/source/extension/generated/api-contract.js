// GENERATED FILE - DO NOT EDIT.
// Source: contracts/openapi/openapi.yaml

((global) => {
  "use strict";

  const objectCreate = Object.create;
  const objectDefineProperty = Object.defineProperty;
  const objectFreeze = Object.freeze;
  const objectKeys = Object.keys;
  const arrayIsArray = Array.isArray;
  const arrayMap = Function.call.bind(Array.prototype.map);
  const jsonParse = JSON.parse;

  const toSafeFrozenValue = (value) => {
    if (arrayIsArray(value)) {
      return objectFreeze(arrayMap(value, toSafeFrozenValue));
    }
    if (value && typeof value === "object") {
      const safe = objectCreate(null);
      for (const key of objectKeys(value)) {
        safe[key] = toSafeFrozenValue(value[key]);
      }
      return objectFreeze(safe);
    }
    return value;
  };

  const operations = toSafeFrozenValue(jsonParse("{\n  \"analyzeText\": {\n    \"method\": \"POST\",\n    \"path\": \"/analyze\",\n    \"queryParameters\": [],\n    \"responses\": {\n      \"200\": [\n        \"application/json\"\n      ],\n      \"400\": [\n        \"application/json\"\n      ],\n      \"401\": [\n        \"application/json\"\n      ],\n      \"402\": [\n        \"application/json\"\n      ],\n      \"403\": [\n        \"application/json\"\n      ],\n      \"422\": [\n        \"application/json\"\n      ],\n      \"429\": [\n        \"application/json\"\n      ],\n      \"500\": [\n        \"application/json\"\n      ]\n    },\n    \"successStatuses\": [\n      \"200\"\n    ]\n  },\n  \"closeAuthSession\": {\n    \"method\": \"POST\",\n    \"path\": \"/auth/logout\",\n    \"queryParameters\": [],\n    \"responses\": {\n      \"200\": [\n        \"application/json\"\n      ],\n      \"401\": [\n        \"application/json\"\n      ],\n      \"422\": [\n        \"application/json\"\n      ]\n    },\n    \"successStatuses\": [\n      \"200\"\n    ]\n  },\n  \"createAuthSession\": {\n    \"method\": \"POST\",\n    \"path\": \"/auth/login\",\n    \"queryParameters\": [],\n    \"responses\": {\n      \"200\": [\n        \"application/json\"\n      ],\n      \"400\": [\n        \"application/json\"\n      ],\n      \"401\": [\n        \"application/json\"\n      ],\n      \"422\": [\n        \"application/json\"\n      ]\n    },\n    \"successStatuses\": [\n      \"200\"\n    ]\n  },\n  \"createBillingCheckout\": {\n    \"method\": \"POST\",\n    \"path\": \"/billing/checkout\",\n    \"queryParameters\": [],\n    \"responses\": {\n      \"200\": [\n        \"application/json\"\n      ],\n      \"400\": [\n        \"application/json\"\n      ],\n      \"401\": [\n        \"application/json\"\n      ],\n      \"403\": [\n        \"application/json\"\n      ],\n      \"409\": [\n        \"application/json\"\n      ],\n      \"422\": [\n        \"application/json\"\n      ],\n      \"502\": [\n        \"application/json\"\n      ]\n    },\n    \"successStatuses\": [\n      \"200\"\n    ]\n  },\n  \"createChatReply\": {\n    \"method\": \"POST\",\n    \"path\": \"/chat\",\n    \"queryParameters\": [],\n    \"responses\": {\n      \"200\": [\n        \"application/json\"\n      ],\n      \"400\": [\n        \"application/json\"\n      ],\n      \"401\": [\n        \"application/json\"\n      ],\n      \"402\": [\n        \"application/json\"\n      ],\n      \"403\": [\n        \"application/json\"\n      ],\n      \"422\": [\n        \"application/json\"\n      ],\n      \"429\": [\n        \"application/json\"\n      ],\n      \"500\": [\n        \"application/json\"\n      ]\n    },\n    \"successStatuses\": [\n      \"200\"\n    ]\n  },\n  \"createPagePreload\": {\n    \"method\": \"POST\",\n    \"path\": \"/pages/preload\",\n    \"queryParameters\": [],\n    \"responses\": {\n      \"202\": [\n        \"application/json\"\n      ],\n      \"400\": [\n        \"application/json\"\n      ],\n      \"401\": [\n        \"application/json\"\n      ],\n      \"402\": [\n        \"application/json\"\n      ],\n      \"403\": [\n        \"application/json\"\n      ],\n      \"409\": [\n        \"application/json\"\n      ],\n      \"422\": [\n        \"application/json\"\n      ],\n      \"429\": [\n        \"application/json\"\n      ],\n      \"500\": [\n        \"application/json\"\n      ]\n    },\n    \"successStatuses\": [\n      \"202\"\n    ]\n  },\n  \"getAuthConfig\": {\n    \"method\": \"GET\",\n    \"path\": \"/auth/config\",\n    \"queryParameters\": [],\n    \"responses\": {\n      \"200\": [\n        \"application/json\"\n      ]\n    },\n    \"successStatuses\": [\n      \"200\"\n    ]\n  },\n  \"getBillingSummary\": {\n    \"method\": \"GET\",\n    \"path\": \"/billing/me\",\n    \"queryParameters\": [],\n    \"responses\": {\n      \"200\": [\n        \"application/json\"\n      ],\n      \"401\": [\n        \"application/json\"\n      ],\n      \"403\": [\n        \"application/json\"\n      ],\n      \"422\": [\n        \"application/json\"\n      ]\n    },\n    \"successStatuses\": [\n      \"200\"\n    ]\n  },\n  \"getPagePreload\": {\n    \"method\": \"GET\",\n    \"path\": \"/pages/preload\",\n    \"queryParameters\": [\n      {\n        \"explode\": true,\n        \"name\": \"page_url\",\n        \"repeat\": false,\n        \"required\": true,\n        \"style\": \"form\"\n      }\n    ],\n    \"responses\": {\n      \"200\": [\n        \"application/json\"\n      ],\n      \"401\": [\n        \"application/json\"\n      ],\n      \"403\": [\n        \"application/json\"\n      ],\n      \"422\": [\n        \"application/json\"\n      ]\n    },\n    \"successStatuses\": [\n      \"200\"\n    ]\n  },\n  \"getVocabularyBook\": {\n    \"method\": \"GET\",\n    \"path\": \"/vocabulary\",\n    \"queryParameters\": [],\n    \"responses\": {\n      \"200\": [\n        \"application/json\"\n      ],\n      \"401\": [\n        \"application/json\"\n      ],\n      \"403\": [\n        \"application/json\"\n      ],\n      \"422\": [\n        \"application/json\"\n      ]\n    },\n    \"successStatuses\": [\n      \"200\"\n    ]\n  },\n  \"openBillingPortal\": {\n    \"method\": \"POST\",\n    \"path\": \"/billing/portal\",\n    \"queryParameters\": [],\n    \"responses\": {\n      \"200\": [\n        \"application/json\"\n      ],\n      \"401\": [\n        \"application/json\"\n      ],\n      \"403\": [\n        \"application/json\"\n      ],\n      \"404\": [\n        \"application/json\"\n      ],\n      \"422\": [\n        \"application/json\"\n      ],\n      \"502\": [\n        \"application/json\"\n      ]\n    },\n    \"successStatuses\": [\n      \"200\"\n    ]\n  }\n}"));
  const operationFields = toSafeFrozenValue([
    ...new Set(
      objectKeys(operations).flatMap((operationId) => objectKeys(operations[operationId])),
    ),
  ].sort());
  const namespace = toSafeFrozenValue({ operationFields, operations });

  objectDefineProperty(global, "UntangleApiContract", {
    value: namespace,
    writable: false,
    configurable: false,
    enumerable: true,
  });
})(globalThis);

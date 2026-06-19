// Plain-language credential "auth methods" shown to users. The user never sees
// n8n credential type names (httpHeaderAuth, etc.) — each friendly method maps
// to an n8n credential type and knows how to build its credential `data`.

export interface AuthMethodField {
  name: string;
  label: string;
  type?: "text" | "password" | "json";
  placeholder?: string;
  advanced?: boolean;
  default?: string;
}

export interface AuthMethod {
  id: string;
  credentialType: string; // n8n credential type
  label: string; // plain language
  description?: string;
  fields: AuthMethodField[];
  buildData: (values: Record<string, string>) => Record<string, unknown>;
  advanced?: boolean; // secondary method, surfaced under "Advanced"
}

export const AUTH_METHODS: AuthMethod[] = [
  {
    id: "api_key",
    credentialType: "httpHeaderAuth",
    label: "API key / token",
    description: "A secret key or token the service gave you.",
    fields: [
      { name: "key", label: "API key or token", type: "password" },
      {
        name: "header",
        label: "Header name",
        type: "text",
        advanced: true,
        default: "Authorization",
      },
      {
        name: "prefix",
        label: "Prefix (leave blank if none)",
        type: "text",
        advanced: true,
        default: "Bearer",
      },
    ],
    buildData: (values) => {
      const header = (values.header ?? "Authorization").trim() || "Authorization";
      const prefix = (values.prefix ?? "Bearer").trim();
      const key = (values.key ?? "").trim();
      return { name: header, value: prefix ? `${prefix} ${key}` : key };
    },
  },
  {
    id: "basic",
    credentialType: "httpBasicAuth",
    label: "Username & password",
    description: "Sign in with a username and password.",
    fields: [
      { name: "user", label: "Username", type: "text" },
      { name: "password", label: "Password", type: "password" },
    ],
    buildData: (values) => ({
      user: values.user ?? "",
      password: values.password ?? "",
    }),
  },
  {
    id: "query",
    credentialType: "httpQueryAuth",
    label: "API key in the URL",
    description: "The key is added to the request URL as a query parameter.",
    advanced: true,
    fields: [
      { name: "name", label: "Parameter name", type: "text", default: "api_key" },
      { name: "value", label: "API key", type: "password" },
    ],
    buildData: (values) => ({
      name: (values.name ?? "api_key").trim() || "api_key",
      value: values.value ?? "",
    }),
  },
  {
    id: "custom",
    credentialType: "httpCustomAuth",
    label: "Custom (advanced)",
    description: "Define headers, query, or body as JSON.",
    advanced: true,
    fields: [{ name: "json", label: "Auth JSON", type: "json" }],
    buildData: (values) => ({ json: values.json ?? "" }),
  },
];

const METHOD_BY_TYPE = new Map(AUTH_METHODS.map((method) => [method.credentialType, method]));

export function methodForCredentialType(type: string): AuthMethod {
  return METHOD_BY_TYPE.get(type) ?? AUTH_METHODS[0];
}

// Friendly label for a stored credential's n8n type (used in lists/badges).
export function friendlyTypeLabel(type: string): string {
  return METHOD_BY_TYPE.get(type)?.label ?? type;
}

// Default field values (e.g. Authorization / Bearer) for a method.
export function defaultValues(method: AuthMethod): Record<string, string> {
  const values: Record<string, string> = {};
  for (const field of method.fields) {
    if (field.default !== undefined) values[field.name] = field.default;
  }
  return values;
}

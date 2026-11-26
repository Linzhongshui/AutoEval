import type { Resource } from "../evaluation/types";

export type SshHost = { key: string; label: string; resources: Resource[] };

export function groupSshHosts(resources: Resource[]): SshHost[] {
  const hosts = new Map<string, SshHost>();
  for (const resource of resources) {
    const address = resource.host?.trim().toLowerCase().replace(/^\[|\]$/g, "").replace(/\.$/, "");
    const port = resource.port ?? 22;
    const key = address ? JSON.stringify([address, port]) : resource.id;
    let group = hosts.get(key);
    if (!group) {
      const label = address ? `${address.includes(":") ? `[${address}]` : address}:${port}` : resource.binding_key;
      group = { key, label, resources: [] };
      hosts.set(key, group);
    }
    group.resources.push(resource);
  }
  return [...hosts.values()];
}

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { Skills } from "./Skills";

afterEach(cleanup);

it.each([true, false])("shows TerraQuake only when assigned (%s)", async (assigned) => {
  const apiFetch = vi.fn(async (path: string) => {
    const data = {
      "/api/v1/channels/whatsapp": { configured: true, agent_name: "primary" },
      "/api/v1/channels/telegram": { configured: false },
      "/api/v1/agents/whatsapp/primary/skills": {
        capabilities: assigned ? ["terraquake.earthquakes"] : [],
        available_capabilities: ["terraquake.earthquakes"],
      },
      "/api/v1/skills/presentations": { terraquake: { name: "TerraQuake", description: "Consulta sismos" } },
      "/api/v1/skills/seerr/configuration": { last_test: "Conexión comprobada" },
    }[path];
    return new Response(JSON.stringify(data), { status: data ? 200 : 404 });
  });
  render(<Skills apiFetch={apiFetch}/>);
  await screen.findByText("Conexión comprobada");
  expect(apiFetch).toHaveBeenCalledWith("/api/v1/agents/whatsapp/primary/skills");
  if (assigned) {
    fireEvent.click(await screen.findByRole("button", { name: /TerraQuake/ }));
    expect(screen.getByText("ACCESO · Catálogo público · sin clave de API")).toBeTruthy();
    expect(screen.queryByLabelText(/clave de API/i)).toBeNull();
    expect(apiFetch).not.toHaveBeenCalledWith("/api/v1/skills/terraquake/configuration");
  } else {
    expect(screen.queryByRole("button", { name: /TerraQuake/ })).toBeNull();
  }
});

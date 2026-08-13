import { BenchmarkWorkbench } from "./ui";

const workbench = new BenchmarkWorkbench();

workbench.init().catch((error: unknown) => {
  const message = error instanceof Error ? error.message : String(error);
  document.querySelector("#world-host")?.replaceChildren(document.createTextNode(message));
});

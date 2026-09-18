const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const scripts = path.join(__dirname, "..", "scripts");
const filename = fs.readdirSync(scripts).find(name => name.endsWith(".html"));
const html = fs.readFileSync(path.join(scripts, filename), "utf8");
const source = html.match(/<script>([\s\S]*?)<\/script>/)[1];
new vm.Script(source); // Check the complete viewer, not just the formatters.
const start = source.indexOf("    function formatValue(");
const end = source.indexOf("    async function loadFiles(", start);
const context = vm.createContext({});
vm.runInContext(source.slice(start, end), context);

const action = { id: "Example", args: {
  composition: { BATTLECRUISER: { proportion: 1, priority: 0 } },
  unit: "7", enabled: true, target: "enemy_main", path: "C:\\new\\test",
} };
assert.equal(context.formatAction(action),
  'Example(composition={BATTLECRUISER: {proportion: 1, priority: 0}}, unit="7", enabled=true, target=enemy_main, path="C:\\\\new\\\\test")');

const reply = '# phase\nopening\n\n# actions\nBroken("quoted")';
const feedback = [{ kind: "output_format", submitted_output: reply, error: "Invalid output" }];
const log = JSON.stringify({ reply, validation_feedback: feedback }) + "\n";
const rows = context.parseJsonl(log, "model.jsonl");
assert.equal(rows[0].reply, reply);
const displayed = context.formatFields(rows[0].validation_feedback);
assert.ok(displayed.includes('     # phase\n     opening'));
assert.ok(displayed.includes('Broken("quoted")'));
assert.ok(!displayed.includes('\\n'));
assert.ok(!displayed.includes('"submitted_output":'));
assert.equal(context.formatFields("C:\\new\\test"), "C:\\new\\test");
assert.equal(context.formatFields('\\n'), '\\n');
assert.equal(context.formatFields([]), "[None]");
assert.ok(context.formatFields({ actions: [action] }).includes("1. Example("));
assert.ok(context.formatFeedback([
  { kind: "action_format", action_index: 2, submitted_action: "Broken(", error: "Syntax" },
  { kind: "phase", submitted_phase: "unknown", error: "Phase" },
  { kind: "action", action, error: "Action" },
]).includes("1. Action: Broken("));
assert.throws(() => context.parseJsonl("{broken}", "model.jsonl"));

// Verify raw output and validation feedback have separate homes, including legacy logs.
context.indexes = { model: new Map([[1, [{ reply, validation_feedback: feedback, actions: [action] }]]]) };
context.line = (label, value) => label + ": " + value;
context.pre = value => value;
let panel;
context.replacePanel = (_id, children) => { panel = children; };
context.fold = (label, content) => label + ": " + content;
vm.runInContext(source.slice(source.indexOf("    function modelRecords("), source.indexOf("    const executionEvents")), context);
context.renderModel(1);
assert.ok(panel.includes(reply));
assert.ok(!panel.some(value => value.includes("Error: Invalid output")));
context.renderValidation(1);
assert.ok(panel.some(value => value.includes("Error: Invalid output")));
context.indexes.model.set(2, [
  { stage: "request", request_body: { messages: [] } },
  { stage: "response", reply, usage: { prompt_tokens: 123, completion_tokens: 45 }, latency_ms: 30 },
  { stage: "parsed", phase: "opening", actions: [action], parse_report: { valid: true, errors: [] } },
  { stage: "validated", validation_report: [{ parsed_index: 1, status: "passed" }] },
]);
context.renderModel(2);
assert.ok(panel.includes(reply));
assert.ok(panel.some(value => value.includes("45")));
context.renderValidation(2);
assert.ok(panel.some(value => value.includes("passed")));
console.log("Viewer syntax, legacy/new records, raw output and separate validation panels passed.");

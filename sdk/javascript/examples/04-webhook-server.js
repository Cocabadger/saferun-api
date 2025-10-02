import express from "express";

const app = express();
app.use(express.json());

app.post("/webhook/saferun", (req, res) => {
  const { event, change_id: changeId, status } = req.body ?? {};
  console.log("SafeRun webhook", event, changeId, status);
  res.json({ ok: true });
});

app.listen(8000, () => {
  console.log("Listening on http://localhost:8000/webhook/saferun");
});

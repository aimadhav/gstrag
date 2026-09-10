"use client";
import { useState } from "react";

export default function Home() {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  async function ask() {
    const response = await fetch("http://localhost:8000/api/chat", { method: "POST", headers: { "Content-Type": "application/json", "X-User-Role": "plus" }, body: JSON.stringify({ question }) });
    const data = await response.json();
    setAnswer(data.answer + (data.review_reason ? `\n\nReview: ${data.review_reason}` : ""));
  }
  return <main style={{ maxWidth: 760, margin: "4rem auto", fontFamily: "sans-serif" }}><h1>GST RAG Assistant</h1><p>Role-aware, cited GST answers. Informational use only.</p><textarea rows={5} value={question} onChange={e => setQuestion(e.target.value)} placeholder="Ask a GST question..." style={{ width: "100%" }} /><button onClick={ask} style={{ marginTop: 12 }}>Ask</button>{answer && <pre style={{ whiteSpace: "pre-wrap", marginTop: 24 }}>{answer}</pre>}</main>;
}

//user.js

/* ============================
   GLOBAL FETCH INTERCEPTOR
============================= */
(function() {
  const originalFetch = window.fetch;
  window.fetch = function(url, options) {
    options = options || {};
    options.headers = options.headers || {};
    const email = localStorage.getItem("userEmail");
    if (email) {
      if (options.headers instanceof Headers) {
        options.headers.set('X-User-Email', email);
      } else {
        options.headers['X-User-Email'] = email;
      }
    }
    return originalFetch(url, options).then(response => {
      if (response.status === 401 && !url.includes('/api/login') && !url.includes('/api/register')) {
        localStorage.removeItem("role");
        localStorage.removeItem("userEmail");
        localStorage.removeItem("userName");
        window.location.href = "index.html";
      }
      return response;
    });
  };
})();

/* ============================
   AUTH GUARD
============================= */
(function() {
  if (localStorage.getItem("role") !== "user") {
    window.location.href = "index.html";
  }
})();

/* ============================
   AI SUGGESTION ENGINE
============================= */
const AI_RULES = [
  // Severity-triggering subjects — always escalate if these keywords appear
  { keywords:["hacked","unauthorized","fraud","fraudulent","stolen","breach","someone accessed","suspicious login","identity theft"],
    suggestion:"⚠️ Security / Account Compromise — Escalating directly to a human agent for security review. Do not share credentials.", priority:"Critical" },
  { keywords:["smoke","burning smell","caught fire","sparking","overheating badly","explod"],
    suggestion:"🔥 Safety Hazard Detected — Potential physical risk reported. Routing immediately to a human agent.", priority:"Critical" },
  { keywords:["lost all","permanently deleted","no backup","everything is gone","lost my data","lost everything"],
    suggestion:"💾 Irreversible Data Loss Risk — Escalating to a human agent to prevent further data damage.", priority:"Critical" },
  { keywords:["double charged","charged twice","unauthorized charge","wrong amount charged","overcharged"],
    suggestion:"💳 Billing Dispute — Incorrect charge detected. Escalating to a human agent for financial correction.", priority:"High" },
  // Refund & cancellation
  { keywords:["refund","money back","reimburse","return"],
    suggestion:"Refund Request — Eligibility checked against 30-day policy window. AI can assist if within window.", priority:"Medium" },
  { keywords:["cancel","terminate","close account","stop renewal"],
    suggestion:"Cancellation Request — Checking 14-day policy window. AI can assist if within window.", priority:"Medium" },
  // Billing & account access
  { keywords:["payment","charged","transaction","gateway","declined","card","invoice","billing","subscription","plan","upgrade"],
    suggestion:"Billing Inquiry — Review payment method, subscription status, and billing cycle.", priority:"Medium" },
  { keywords:["login","password","sign in","access denied","locked","authenticate","2fa","otp","account access"],
    suggestion:"Account Access Issue — Password reset or account recovery. Checking for prior resolution contradictions.", priority:"High" },
  // Hardware & battery & display
  { keywords:["battery","battery life","draining","dies fast","loses charge","won't charge","charge"],
    suggestion:"Battery Life Issue — Checking warranty window (365 days) and prior repair records for contradictions.", priority:"High" },
  { keywords:["screen","display","flickering","distorted","lines on screen","discolored","cracked screen","glitch"],
    suggestion:"Display Issue — Checking prior repair records and attempt count.", priority:"High" },
  { keywords:["device","hardware","cable","laptop","pc","printer","broken","defective","stopped working","won't turn on","warranty"],
    suggestion:"Hardware Issue — Checking 12-month warranty window and prior repair contradictions.", priority:"High" },
  // Software & network
  { keywords:["crash","error","bug","broken","not working","doesn't work","fail","since the update","after updating"],
    suggestion:"Software Bug — Checking 60-day post-update grace period and prior fix contradictions.", priority:"High" },
  { keywords:["slow","performance","lagging","timeout","loading","wifi","internet","network","ping","offline","connect"],
    suggestion:"Network Problem — Verify connectivity and server status. Checking troubleshooting attempt count.", priority:"Medium" },
  // Installation, setup & product
  { keywords:["install","reinstall","won't open","won't launch","won't start","crashes on open","installation"],
    suggestion:"Installation Support — Checking installation completion records for contradictions.", priority:"High" },
  { keywords:["setup","configure","initialize","set up","won't connect","stuck on setup"],
    suggestion:"Product Setup — Checking setup completion records and attempt count.", priority:"Low" },
  { keywords:["peripheral","keyboard","mouse","headset","controller","won't pair","won't connect","not detected","not recognized"],
    suggestion:"Peripheral Compatibility — Checking compatibility records and pairing attempt count.", priority:"High" },
  { keywords:["compatible","compatibility","works with","product compatibility","sync","pair"],
    suggestion:"Product Compatibility — ML classifier assessing compatibility patterns.", priority:"Medium" },
  // Data loss
  { keywords:["data loss","files missing","lost files","deleted files","data recovery","restore files"],
    suggestion:"Data Loss — Checking severity risk and prior recovery records for contradictions.", priority:"High" },
  // Delivery
  { keywords:["delivery","shipped","shipping","package","courier","deliver","order"],
    suggestion:"Delivery Problem — Checking 10-day delivery SLA and carrier records.", priority:"Medium" },
  // Product inquiry & recommendation
  { keywords:["feature","how to","pricing","specs","documentation","recommend","suggestion","which product"],
    suggestion:"Product Inquiry / Recommendation — ML classifier assessing query patterns.", priority:"Low" },
];


function analyzeTicket(text, category) {
  const lower = text.toLowerCase() + " " + (category||"").toLowerCase();
  for (const rule of AI_RULES) {
    if (rule.keywords.some(k => lower.includes(k))) return rule;
  }
  return { suggestion:"General Support Request — Routed to first-available agent.", priority:"Low" };
}

/* ============================
   CATEGORY: "OTHER" HANDLING
============================= */
function handleCategoryChange() {
  const cat   = document.getElementById("category").value;
  const group = document.getElementById("otherCategoryGroup");
  if (cat === "Other" || cat === "other") {
    group.classList.add("show");
    document.getElementById("otherCategory").focus();
  } else {
    group.classList.remove("show");
    document.getElementById("otherCategory").value = "";
  }
  updateAISuggestion();
}

function updateAISuggestion() {
  const desc = document.getElementById("description").value;
  const cat  = document.getElementById("category").value;
  const box  = document.getElementById("aiLiveBox");
  const txt  = document.getElementById("aiLiveText");
  const pri  = document.getElementById("priority");

  if (desc.length < 8 && !cat) { box.classList.remove("show"); return; }

  const result = analyzeTicket(desc, cat);
  txt.innerText = result.suggestion;
  if (pri && result.priority) pri.value = result.priority;
  box.classList.add("show");
}

/* ============================
   SUBMIT TICKET
============================= */
let pendingTicketData = null;

function getHelpArticleKey(category) {
  if (!category) return "other";
  const cat = category.toLowerCase();
  if (cat.includes("technical")) return "technical";
  if (cat.includes("billing")) return "billing";
  if (cat.includes("payment")) return "billing";
  if (cat.includes("product inquiry")) return "product";
  if (cat.includes("product recommendation")) return "recommendation";
  if (cat.includes("product compatibility")) return "compatibility";
  if (cat.includes("compatibility")) return "compatibility";
  if (cat.includes("refund")) return "refund";
  if (cat.includes("cancellation")) return "cancellation";
  if (cat.includes("setup")) return "setup";
  if (cat.includes("hardware")) return "hardware";
  if (cat.includes("battery")) return "battery";
  if (cat.includes("display")) return "display";
  if (cat.includes("peripheral")) return "peripheral";
  if (cat.includes("installation")) return "installation";
  if (cat.includes("data loss")) return "data";
  if (cat.includes("data")) return "data";
  if (cat.includes("delivery")) return "delivery";
  if (cat.includes("network")) return "network";
  if (cat.includes("bug")) return "bug";
  if (cat.includes("software")) return "bug";
  if (cat.includes("account")) return "account";
  return "other";
}


function submitTicket() {
  const name  = document.getElementById("name").value.trim();
  const email = document.getElementById("email").value.trim();
  let   cat   = document.getElementById("category").value;
  const desc  = document.getElementById("description").value.trim();
  const subject = document.getElementById("subject").value;
  const priority = document.getElementById("priority").value;
  const contactChannel = document.getElementById("contactChannel").value;
  const productPurchased = document.getElementById("productPurchased").value;

  // If "other", use the custom input as category
  if (cat === "Other" || cat === "other") {
    const custom = document.getElementById("otherCategory").value.trim();
    if (!custom) { showToast("error","Missing Info","Please describe your issue type in the field below Category."); return; }
    cat = "other: " + custom;
  }

  if (!name || !email || !cat || !desc || !subject || !contactChannel || !productPurchased) {
    showToast("error","Missing Fields","Please fill in all required fields.");
    return;
  }
  if (!email.includes("@")) {
    showToast("error","Invalid Email","Please enter a valid email address.");
    return;
  }

  const analysis = analyzeTicket(desc, cat);

  pendingTicketData = {
    email: email,
    category: cat,
    description: desc,
    priority: priority,
    aiSuggestion: analysis.suggestion,
    status: 'Open',
    subject: subject,
    contactChannel: contactChannel,
    productPurchased: productPurchased
  };

  // Show AI prediction modal loading state
  document.getElementById("aiPredictionModal").classList.add("show");
  document.getElementById("aiPredictionLoading").style.display = "block";
  document.getElementById("aiPredictionYes").style.display = "none";
  document.getElementById("aiPredictionNo").style.display = "none";

  // Fetch prediction from backend
  fetch('/api/predict_ticket', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(pendingTicketData)
  })
  .then(res => res.json())
  .then(data => {
    document.getElementById("aiPredictionLoading").style.display = "none";
    if (data.success) {
      // Store the dynamic explanation from rules engine / ML fallback
      pendingTicketData.aiSuggestion = data.reason;

      if (data.prediction === "yes") {
        // Send auto-resolved notification to user
        addNotification(`AI Auto-Resolution: Your request for <strong>${pendingTicketData.category}</strong> was solved directly by AI.`);
        
        // Populate and display details
        const detailsContainer = document.getElementById("aiResolutionDetails");
        if (detailsContainer) {
          const articleKey = getHelpArticleKey(pendingTicketData.category);
          const article = HELP_ARTICLES[articleKey];
          
          let stepsHtml = "";
          if (article && article.steps) {
            stepsHtml = `
              <div style="margin-top: 12px; border-top: 1px solid rgba(255,255,255,0.08); padding-top: 12px;">
                <strong style="color: #38bdf8; font-size: 13px;">AI Suggested Troubleshooting Steps:</strong>
                <ul style="margin-top: 8px; padding-left: 20px; color: #cbd5e1; font-size: 13px; line-height: 1.6;">
                  ${article.steps.map(step => `<li>${step}</li>`).join("")}
                </ul>
              </div>
            `;
          }
          
          detailsContainer.innerHTML = `
            <div style="font-size: 14px; color: #cbd5e1; font-weight: 600; margin-bottom: 6px;">AI Insight:</div>
            <div style="font-size: 13px; color: #38bdf8; line-height: 1.5; font-style: italic; font-weight: 500;">"${data.reason}"</div>
            ${stepsHtml}
          `;
        }
        
        document.getElementById("aiPredictionYes").style.display = "block";
      } else {
        // Send not-solved notification to user
        addNotification(`AI Auto-Resolution: AI could not solve your request for <strong>${pendingTicketData.category}</strong>. Further assistance required.`);
        
        const noDetails = document.getElementById("aiPredictionNoDetails");
        if (noDetails) {
          noDetails.innerHTML = `
            <div style="font-weight: 600; color: #f87171; margin-bottom: 6px;">AI Insight:</div>
            <div style="font-style: italic;">"${data.reason}"</div>
          `;
        }
        document.getElementById("aiPredictionNo").style.display = "block";
      }
    } else {
      document.getElementById("aiPredictionModal").classList.remove("show");
      showToast("error", "AI Analysis Failed", data.message || "Proceeding to normal ticket submission.");
      proceedToRaiseTicket();
    }
  })
  .catch(err => {
    console.error(err);
    document.getElementById("aiPredictionLoading").style.display = "none";
    document.getElementById("aiPredictionModal").classList.remove("show");
    showToast("error", "Connection Error", "AI prediction could not be completed. Proceeding to normal submission.");
    proceedToRaiseTicket();
  });
}

function closeAiPredictionModal(isSolved) {
  document.getElementById("aiPredictionModal").classList.remove("show");
  if (isSolved) {
    if (!pendingTicketData) {
      clearForm();
      showToast("success", "Done!", "Issue resolved via AI auto-assistance.");
      return;
    }

    // Build AI resolution note from the suggestion and steps shown
    const detailsEl = document.getElementById("aiResolutionDetails");
    const resolutionText = detailsEl ? detailsEl.innerText.trim() : pendingTicketData.aiSuggestion;
    const solverNote = "AI Auto-Resolved: " + resolutionText;

    // Save the ticket to the database as Resolved
    const resolvedTicketData = Object.assign({}, pendingTicketData, {
      status: 'Resolved',
      solver_note: solverNote
    });

    showToast("info", "Saving...", "Recording AI-resolved ticket...");

    fetch('/api/tickets', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(resolvedTicketData)
    })
    .then(res => res.json())
    .then(data => {
      if (data.success) {
        addNotification(`Ticket <strong>${data.ticket.id}</strong> was resolved by AI and saved to your history.`);
        renderMyTickets();
        clearForm();
        showToast("success", "AI Resolved!", `Ticket ${data.ticket.id} saved as Resolved.`);
      } else {
        clearForm();
        showToast("success", "Done!", "Issue resolved via AI auto-assistance.");
      }
    })
    .catch(() => {
      clearForm();
      showToast("success", "Done!", "Issue resolved via AI auto-assistance.");
    });
  }
}

function proceedToRaiseTicket() {
  document.getElementById("aiPredictionModal").classList.remove("show");
  if (!pendingTicketData) return;

  showToast("info", "Submitting...", "Raising ticket to support solvers...");

  fetch('/api/tickets', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(pendingTicketData)
  })
  .then(res => res.json())
  .then(data => {
    if (data.success) {
      addNotification(
        `Ticket <strong>${data.ticket.id}</strong> submitted successfully.`
      );
      renderMyTickets();
      clearForm();
      showToast("success", "Ticket Raised!", `ID: ${data.ticket.id}`);
    } else {
      showToast("error", "Failed to submit ticket", data.message || "An error occurred.");
    }
  })
  .catch(err => {
    console.error(err);
    showToast("error", "Connection Error", "Failed to connect to the backend server.");
  });
}

function clearForm() {
  ["description","otherCategory","subject","contactChannel","productPurchased"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = "";
  });
  const pri = document.getElementById("priority");
  if (pri) pri.value = "Low";
  document.getElementById("category").value = "";
  document.getElementById("otherCategoryGroup").classList.remove("show");
  document.getElementById("fileLabel").innerText = "Click to upload a screenshot or document";
  document.getElementById("aiLiveBox").classList.remove("show");

  // Re-populate name and email with logged-in user credentials
  const email = localStorage.getItem("userEmail") || "user@gmail.com";
  const name = localStorage.getItem("userName") || email.split("@")[0];
  const userName = name.charAt(0).toUpperCase() + name.slice(1);

  const nameInput = document.getElementById("name");
  if (nameInput) nameInput.value = userName;
  const emailInput = document.getElementById("email");
  if (emailInput) emailInput.value = email;
}

function handleFileSelect(input) {
  if (input.files.length) {
    document.getElementById("fileLabel").innerText = "📎 " + input.files[0].name;
  }
}

/* ============================
   RENDER MY TICKETS
============================= */
function renderMyTickets(filterText="", filterStatus="") {
  const tbody   = document.getElementById("myTicketsBody");
  const empty   = document.getElementById("myTicketsEmpty");

  fetch('/api/tickets')
  .then(response => response.json())
  .then(data => {
    if (data.success) {
      const oldTickets = myTicketsList || [];
      const newTickets = data.tickets || [];
      
      // Detect updates from solver
      if (oldTickets.length > 0) {
        newTickets.forEach(ticket => {
          const old = oldTickets.find(t => t.id === ticket.id);
          if (old) {
            const statusChanged = old.status !== ticket.status;
            const solverNoteChanged = ticket.solverNote && old.solverNote !== ticket.solverNote;
            
            if (statusChanged || solverNoteChanged) {
              const typedMsg = ticket.solverNote ? ` Solver note: "${ticket.solverNote}"` : "";
              addNotification(
                `Your ticket <strong>${ticket.id}</strong> status was updated to <strong>${ticket.status}</strong>.${typedMsg}`
              );
              showToast("info", "Ticket Updated", `Ticket ${ticket.id} is now ${ticket.status}.`);
            }
          }
        });
      }

      myTicketsList = newTickets;
      updateStats(myTicketsList);

      const filtered = [...myTicketsList].reverse().filter(t => {
        const txt = filterText.toLowerCase();
        const matchText = !txt ||
          (t.id||"").toLowerCase().includes(txt) ||
          (t.category||"").toLowerCase().includes(txt) ||
          (t.description||"").toLowerCase().includes(txt);
        const matchStatus = !filterStatus || t.status === filterStatus;
        return matchText && matchStatus;
      });

      tbody.innerHTML = "";
      if (!filtered.length) { empty.style.display="block"; return; }
      empty.style.display = "none";

      filtered.forEach(ticket => {
        const statusClass = (ticket.status||"open").toLowerCase().replace(/\s+/g,"-");
        const priClass    = (ticket.priority||"low").toLowerCase();
        const date = ticket.createdAt
          ? new Date(ticket.createdAt).toLocaleDateString("en-IN",{day:"2-digit",month:"short",year:"numeric"})
          : "—";

        tbody.innerHTML += `
          <tr>
            <td>
              <span style="font-family:'Syne',sans-serif;font-size:13px;color:#38bdf8;">${ticket.id}</span><br>
              <span style="color:#475569;font-size:12px;">${date}</span>
            </td>
            <td style="max-width:120px;">${ticket.category}</td>
            <td style="max-width:180px;color:#94a3b8;font-size:13px;">
              ${(ticket.description||"").substring(0,55)}${(ticket.description||"").length>55?"...":""}
            </td>
            <td><span class="badge ${priClass}">${ticket.priority||"Low"}</span></td>
            <td style="max-width:160px;font-size:13px;color:#94a3b8;">
              ${(ticket.aiSuggestion||"").substring(0,50)}...
            </td>
            <td><span class="badge ${statusClass}">${ticket.status}</span></td>
            <td>
              <button class="btn btn-sm btn-primary" onclick='viewTicket("${ticket.id}")'>
                <i class="fa-solid fa-eye"></i> View
              </button>
            </td>
          </tr>`;
      });
    }
  })
  .catch(err => {
    console.error(err);
    tbody.innerHTML = "";
    empty.style.display = "block";
    empty.querySelector("p").innerText = "Failed to load tickets. Please check your connection.";
  });
}

function filterMyTickets() {
  const text   = document.getElementById("ticketSearch").value.toLowerCase();
  const status = document.getElementById("statusFilter").value;
  renderMyTickets(text, status);
}

/* ============================
   VIEW TICKET MODAL
============================= */
function viewTicket(id) {
  const t = myTicketsList.find(x => x.id === id);
  if (!t) return;

  document.getElementById("modalTitle").innerText = `Ticket ${t.id}`;
  document.getElementById("modalSub").innerText   =
    `Submitted on ${t.createdAt ? new Date(t.createdAt).toLocaleString() : "—"}`;

  const statusClass = (t.status||"pending").toLowerCase().replace(/\s+/g,"-");
  const priClass    = (t.priority||"low").toLowerCase();
  const adminNote   = t.adminNote
    ? `<div style="margin-top:12px;background:rgba(56,189,248,0.06);border:1px solid rgba(56,189,248,0.2);border-radius:12px;padding:14px;">
        <div style="font-size:11px;color:#38bdf8;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px;">Admin Note</div>
        <div style="font-size:14px;color:#cbd5e1;">${t.adminNote}</div>
       </div>` : "";

  const solverNote   = (t.solverNote && !t.solverNote.startsWith('AI Auto-Resolved'))
    ? `<div style="margin-top:12px;background:rgba(34,197,94,0.06);border:1px solid rgba(34,197,94,0.2);border-radius:12px;padding:14px;">
        <div style="font-size:11px;color:#22c55e;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px;">Solver Note</div>
        <div style="font-size:14px;color:#cbd5e1;">${t.solverNote}</div>
       </div>` : "";

  const subjectHtml = t.subject ? `<div class="ai-insight-item"><div class="label">Subject</div><div style="font-size:14px;font-weight:600;margin-top:4px;color:white;">${t.subject}</div></div>` : "";
  const contactChannelHtml = t.contactChannel ? `<div class="ai-insight-item"><div class="label">Contact Channel</div><div style="font-size:14px;font-weight:600;margin-top:4px;color:white;">${t.contactChannel}</div></div>` : "";
  const productPurchasedHtml = t.productPurchased ? `<div class="ai-insight-item"><div class="label">Product Purchased</div><div style="font-size:14px;font-weight:600;margin-top:4px;color:white;">${t.productPurchased}</div></div>` : "";

  document.getElementById("modalBody").innerHTML = `
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:16px;">
      <div class="ai-insight-item"><div class="label">Category</div><div style="font-size:15px;font-weight:600;margin-top:4px;">${t.category}</div></div>
      <div class="ai-insight-item"><div class="label">Status</div><div style="margin-top:4px;"><span class="badge ${statusClass}">${t.status}</span></div></div>
      <div class="ai-insight-item"><div class="label">Priority</div><div style="margin-top:4px;"><span class="badge ${priClass}">${t.priority||"Low"}</span></div></div>
      <div class="ai-insight-item"><div class="label">Submitted By</div><div style="font-size:14px;margin-top:4px;">${t.name}</div></div>
      ${subjectHtml}
      ${contactChannelHtml}
      ${productPurchasedHtml}
    </div>
    <div style="background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);border-radius:14px;padding:16px;margin-bottom:12px;">
      <div style="font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px;">Description</div>
      <div style="font-size:14px;line-height:1.8;color:#cbd5e1;">${t.description}</div>
    </div>
    <div class="ai-live-box show">
      <div class="ai-label"><i class="fa-solid fa-robot"></i> &nbsp;AI Analysis</div>
      <div class="ai-text">${t.aiSuggestion}</div>
    </div>
    ${adminNote}${solverNote}
    ${t.solverNote && t.solverNote.startsWith('AI Auto-Resolved') ? `
      <div style="margin-top:16px;background:linear-gradient(135deg,rgba(56,189,248,0.08),rgba(99,102,241,0.08));border:2px solid rgba(56,189,248,0.3);border-radius:14px;padding:18px;">
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;">
          <div style="width:32px;height:32px;border-radius:8px;background:rgba(56,189,248,0.15);display:flex;align-items:center;justify-content:center;">
            <i class='fa-solid fa-robot' style='color:#38bdf8;font-size:15px;'></i>
          </div>
          <div style="font-size:12px;font-weight:700;color:#38bdf8;text-transform:uppercase;letter-spacing:0.8px;">Resolved by AI</div>
          <span class="badge resolved" style="margin-left:auto;font-size:11px;">Auto-Resolved</span>
        </div>
        <div style="font-size:13px;color:#cbd5e1;line-height:1.75;">${t.solverNote.replace('AI Auto-Resolved: ', '')}</div>
      </div>` : ''}`;

  document.getElementById("ticketModal").classList.add("show");
}

function closeModal() {
  document.getElementById("ticketModal").classList.remove("show");
}

/* ============================
   HELP CENTRE ARTICLES
============================= */
const HELP_ARTICLES = {
  technical:{
    title:"Technical Issue",
    sub:"Performance, crashes, and other technical problems",
    steps:[
      "Restart the application or refresh your browser.",
      "Clear your browser cache and cookies (Settings → Privacy).",
      "Disable browser extensions to isolate conflicts.",
      "Check our status page at status.resolvex.com for outages."
    ]
  },
  billing:{
    title:"Billing Inquiry",
    sub:"Invoices, subscription cycles, and charges",
    steps:[
      "Review your transaction history in Profile → Billing.",
      "Verify your payment method is active and up to date.",
      "Billing cycles process automatically on your cycle date.",
      "For duplicate charge queries, wait 24-48 hours for reversal."
    ]
  },
  product:{
    title:"Product Inquiry",
    sub:"Features, specifications, and licensing",
    steps:[
      "Browse our documentation at docs.resolvex.com.",
      "Check feature specifications and release notes.",
      "View tutorials and product walkthroughs.",
      "For custom pricing plans, contact sales@resolvex.com."
    ]
  },
  refund:{
    title:"Refund Request",
    sub:"Eligibility, timelines, and refund process",
    steps:[
      "Refund requests are eligible within 30 days of purchase (our SLA policy window).",
      "Check if your plan is under an active free-trial period.",
      "Approved refunds process in 5-10 business days.",
      "Provide your order ID and invoice code on request.",
      "If marked refunded but not received, contact support immediately — this is treated as a priority contradiction case."
    ]
  },
  cancellation:{
    title:"Cancellation Request",
    sub:"Cancelling subscription plans and renewals",
    steps:[
      "Go to Profile → Subscriptions → Cancel Subscription.",
      "Cancellations within 14 days are handled automatically by AI.",
      "Cancellations halt renewals; plan remains active until end of cycle.",
      "Check for a verification email confirming cancellation.",
      "If marked cancelled but still being charged, contact support — this is a priority contradiction case."
    ]
  },
  setup:{
    title:"Product Setup",
    sub:"Quick start guides and configuration parameters",
    steps:[
      "Refer to the Quick-Start Setup Guide in docs.",
      "Ensure device meets minimum compatibility requirements.",
      "Verify setup configuration parameters and connection strings.",
      "Run the diagnostic installer tool if setup fails.",
      "If setup shows complete but device still doesn't work, raise a ticket — this is a contradiction that needs human review."
    ]
  },
  hardware:{
    title:"Hardware Issue",
    sub:"Device diagnostics and hardware setups",
    steps:[
      "Verify device power connection and cables.",
      "Run built-in system diagnostics on the device.",
      "Check device manager for active hardware driver updates.",
      "Restart the hardware component and retry.",
      "Hardware issues within the 12-month warranty window are prioritised. If marked repaired but still faulty, raise a ticket immediately."
    ]
  },
  bug:{
    title:"Software Bug",
    sub:"Application errors and script failures",
    steps:[
      "Note the actions taken to reproduce the bug.",
      "Collect screenshots or error logs from F12 console.",
      "Test if bug persists across different browsers/devices.",
      "Refresh the page to reload active scripts.",
      "Bugs reported within 60 days of a software update are within the grace period and AI can assist first."
    ]
  },
  network:{
    title:"Network Problem",
    sub:"Bandwidth, firewalls, and routers",
    steps:[
      "Reboot router/modem and check ethernet connections.",
      "Run a network speed test to measure bandwidth.",
      "Temporarily disable VPN/proxy connections.",
      "Verify firewall settings permit server access.",
      "If you've already tried these steps more than twice, raise a ticket for human assistance."
    ]
  },
  account:{
    title:"Account Access",
    sub:"Login problems and locked accounts",
    steps:[
      "Use 'Forgot Password' link to request reset email.",
      "Type manual credentials to avoid auto-fill errors.",
      "Check junk/spam folder for recovery or verification emails.",
      "Locked accounts auto-unlock after 15 minutes.",
      "If account shows as unlocked/restored but you still can't get in, raise a ticket — this is a contradiction case."
    ]
  },
  battery:{
    title:"Battery Life Issue",
    sub:"Battery draining, charging problems, and power issues",
    steps:[
      "Check battery health: Settings → Battery → Battery Health.",
      "Reduce screen brightness and disable background apps.",
      "Calibrate battery: drain fully, then charge to 100% uninterrupted.",
      "Check if the issue started after a software update.",
      "Hardware within the 12-month warranty window is eligible for replacement. If marked fixed but still draining, raise a ticket immediately."
    ]
  },
  display:{
    title:"Display Issue",
    sub:"Screen flickering, distortion, discoloration, and visual defects",
    steps:[
      "Adjust display resolution and refresh rate in Settings → Display.",
      "Update graphics/display drivers from Device Manager.",
      "Test with an external monitor to isolate if it's hardware or software.",
      "Restart the device to see if the issue clears.",
      "If the screen was previously repaired/replaced but the same issue continues, raise a ticket — this is a contradiction case."
    ]
  },
  data:{
    title:"Data Loss",
    sub:"Missing files, accidental deletion, and data recovery",
    steps:[
      "Check the Recycle Bin or Trash for recently deleted files.",
      "Search cloud sync services (OneDrive, Google Drive, iCloud) for backups.",
      "Run a system restore to a previous save point if available.",
      "Do NOT save new files to the affected drive — this may overwrite recoverable data.",
      "If a prior recovery was confirmed but files are still missing, raise a ticket immediately — this is a critical contradiction case."
    ]
  },
  peripheral:{
    title:"Peripheral Compatibility",
    sub:"Keyboard, mouse, controller, headset, and device pairing",
    steps:[
      "Ensure the peripheral is listed as compatible with your device/OS version.",
      "Try unplugging and re-plugging the device (or re-pairing for Bluetooth).",
      "Update device drivers from the manufacturer's website.",
      "Try the peripheral on a different port or device to isolate the issue.",
      "If listed as compatible but won't pair or connect, raise a ticket — this is a contradiction case requiring human review."
    ]
  },
  installation:{
    title:"Installation Support",
    sub:"Software installation, setup failures, and app launch issues",
    steps:[
      "Ensure system meets minimum requirements (RAM, OS version, disk space).",
      "Run the installer as Administrator and disable antivirus temporarily.",
      "Clear the temp installation folder and re-download the installer.",
      "Check installation logs for specific error codes.",
      "If installation shows successful but the app won't open or launch, raise a ticket — this is a contradiction case."
    ]
  },
  delivery:{
    title:"Delivery Problem",
    sub:"Shipping delays, lost packages, and tracking issues",
    steps:[
      "Check the tracking number on the courier's website for latest status.",
      "Allow up to 10 business days for standard shipping (our SLA window).",
      "Contact the courier directly if the package shows as in-transit for too long.",
      "Verify the shipping address provided during checkout is correct.",
      "If tracking shows 'Delivered' but you haven't received it, raise a ticket immediately — this is a contradiction case."
    ]
  },
  compatibility:{
    title:"Product Compatibility",
    sub:"Software/hardware compatibility checks",
    steps:[
      "Check the product's official compatibility list on the manufacturer's page.",
      "Ensure OS and firmware versions meet the product's minimum requirements.",
      "Check for driver or firmware updates that may resolve compatibility issues.",
      "Try the product on a different device to narrow down the issue.",
      "If listed as compatible but doesn't actually work, raise a ticket — this is a contradiction case requiring human review."
    ]
  },
  recommendation:{
    title:"Product Recommendation",
    sub:"Choosing the right product for your needs",
    steps:[
      "Browse our comparison guide at docs.resolvex.com/compare.",
      "Filter products by your specific use case, budget, and OS compatibility.",
      "Read user reviews and ratings on the product pages.",
      "Contact our pre-sales team at sales@resolvex.com for personalised advice.",
      "If a recommendation was made but doesn't fit your stated need, raise a ticket — our AI will flag this as a recommendation mismatch."
    ]
  },
  other:{
    title:"General Inquiry",
    sub:"General questions and custom queries",
    steps:[
      "Search our public documentation at docs.resolvex.com.",
      "Check user manual and FAQs for quick references.",
      "Support solvers are available 24/7.",
      "If query is unique, raise a ticket below."
    ]
  }
};


let activeHelpType = "";

function openHelpArticle(type) {
  activeHelpType = type;
  const article = HELP_ARTICLES[type];
  if (!article) return;

  document.getElementById("helpModalTitle").innerText = article.title;
  document.getElementById("helpModalSub").innerText   = article.sub;
  document.getElementById("helpModalBody").innerHTML  =
    `<div style="margin-top:4px;">` +
    article.steps.map((step, i) => `
      <div style="display:flex;gap:14px;align-items:flex-start;padding:12px 0;border-bottom:1px solid rgba(255,255,255,0.05);">
        <div style="width:26px;height:26px;border-radius:50%;background:linear-gradient(135deg,#0ea5e9,#8b5cf6);
          display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700;flex-shrink:0;">${i+1}</div>
        <div style="font-size:14px;color:#cbd5e1;line-height:1.7;padding-top:3px;">${step}</div>
      </div>`).join("") +
    `</div>`;

  document.getElementById("helpModal").classList.add("show");
}

function closeHelpModal() {
  document.getElementById("helpModal").classList.remove("show");
}

function raiseHelpTicket() {
  closeHelpModal();
  
  const categoryMap = {
    technical: "Technical Issue",
    billing: "Billing Inquiry",
    product: "Product Inquiry",
    refund: "Refund Request",
    cancellation: "Cancellation Request",
    setup: "Product Setup",
    hardware: "Hardware Issue",
    bug: "Software Bug",
    network: "Network Problem",
    account: "Account Access",
    other: "other"
  };
  
  const mappedCategory = categoryMap[activeHelpType] || "";
  const sidebarItems = document.querySelectorAll('.sidebar li');
  if (sidebarItems && sidebarItems.length > 0) {
    showSection('create', sidebarItems[0]);
  } else {
    showSection('create', null);
  }
  
  if (mappedCategory) {
    const categorySelect = document.getElementById("category");
    if (categorySelect) {
      categorySelect.value = mappedCategory;
      handleCategoryChange();
    }
  }
}

/* ============================
   STATS
============================= */
function updateStats(tickets) {
  const list = tickets || myTicketsList || [];
  let pending=0, resolved=0;
  list.forEach(t => {
    if (t.status==="Pending" || t.status==="Open" || t.status==="In Progress")  pending++;
    if (t.status==="Solved" || t.status==="Resolved") resolved++;
  });
  document.getElementById("totalCount").innerText   = list.length;
  document.getElementById("pendingCount").innerText  = pending;
  document.getElementById("resolvedCount").innerText = resolved;
}

/* ============================
   NOTIFICATIONS
============================= */
function addNotification(msg) {
  let notifs = JSON.parse(localStorage.getItem("notifications")) || [];
  notifs.unshift({ id:Date.now(), msg, time:new Date().toLocaleString(), read:false });
  localStorage.setItem("notifications", JSON.stringify(notifs));
  updateNotifBadge();
  renderNotifDropdown();
}

function updateNotifBadge() {
  const notifs = JSON.parse(localStorage.getItem("notifications")) || [];
  const unread = notifs.filter(n=>!n.read).length;
  const dot    = document.getElementById("notifDot");
  const badge  = document.getElementById("sidebarBadge");
  if (dot)   { dot.style.display   = unread ? "block" : "none"; }
  if (badge) { badge.style.display = unread ? "inline" : "none"; badge.innerText = unread > 9 ? "9+" : unread; }
}

function markAllRead() {
  let notifs = JSON.parse(localStorage.getItem("notifications")) || [];
  notifs = notifs.map(n => ({...n, read:true}));
  localStorage.setItem("notifications", JSON.stringify(notifs));
  updateNotifBadge();
  renderNotifDropdown();
  renderNotifPage();
}

function clearNotifications() {
  localStorage.removeItem("notifications");
  updateNotifBadge();
  renderNotifDropdown();
  renderNotifPage();
  showToast("info", "Notifications Cleared", "All notifications have been cleared.");
}

function renderNotifDropdown() {
  const notifs = JSON.parse(localStorage.getItem("notifications")) || [];
  const list   = document.getElementById("notifDropdownList");
  if (!list) return;

  if (!notifs.length) {
    list.innerHTML = `<div class="notif-empty"><i class="fa-solid fa-bell-slash"></i>No notifications yet.</div>`;
    return;
  }
  list.innerHTML = notifs.slice(0,5).map(n => `
    <div class="notif-item">
      <div class="notif-dot-item ${n.read?'read':''}"></div>
      <div class="notif-item-text">
        <div class="notif-item-msg">${n.msg}</div>
        <div class="notif-item-time">${n.time}</div>
      </div>
    </div>`).join("") +
    (notifs.length > 5
      ? `<div style="text-align:center;padding:12px;font-size:13px;color:#38bdf8;cursor:pointer;"
           onclick="showSection('notifications',null);closeDropdowns();">
           View all ${notifs.length} notifications →
         </div>`
      : "");
}

function renderNotifPage() {
  const notifs = JSON.parse(localStorage.getItem("notifications")) || [];
  const list   = document.getElementById("notifList");
  if (!list) return;

  if (!notifs.length) {
    list.innerHTML = `<div class="empty-state"><i class="fa-solid fa-bell-slash"></i><p>No notifications yet.</p></div>`;
    return;
  }
  list.innerHTML = notifs.map(n => `
    <div style="display:flex;gap:14px;align-items:flex-start;padding:16px;border-bottom:1px solid rgba(255,255,255,0.05);">
      <div style="width:10px;height:10px;border-radius:50%;background:${n.read?"#334155":"#38bdf8"};margin-top:5px;flex-shrink:0;"></div>
      <div style="flex:1;">
        <div style="font-size:14px;line-height:1.6;color:#cbd5e1;">${n.msg}</div>
        <div style="font-size:12px;color:#475569;margin-top:4px;">${n.time}</div>
      </div>
    </div>`).join("");
}

/* ============================
   SECTION NAVIGATION
============================= */
const SECTIONS = ["create","mytickets","helpcenter","notifications"];
const TITLES   = {
  create:"Create Ticket", mytickets:"My Tickets",
  helpcenter:"Help Centre", notifications:"Notifications"
};

function showSection(name, el) {
  SECTIONS.forEach(s => {
    document.getElementById("section-"+s).style.display = s===name ? "block" : "none";
  });
  document.querySelectorAll(".sidebar li").forEach(li => li.classList.remove("active"));
  if (el) el.classList.add("active");
  document.getElementById("pageTitle").innerText = TITLES[name] || name;

  if (name==="mytickets")     renderMyTickets();
  if (name==="notifications") { renderNotifPage(); markAllRead(); }
}

/* ============================
   TOPBAR DROPDOWN TOGGLES
============================= */
function toggleNotifPanel(e) {
  e.stopPropagation();
  const panel   = document.getElementById("notifPanel");
  const profile = document.getElementById("profilePanel");
  profile.style.display = "none";
  panel.style.display   = panel.style.display==="none" ? "block" : "none";
  if (panel.style.display==="block") renderNotifDropdown();
}

function toggleProfilePanel(e) {
  e.stopPropagation();
  const panel = document.getElementById("profilePanel");
  const notif = document.getElementById("notifPanel");
  notif.style.display  = "none";
  panel.style.display  = panel.style.display==="none" ? "block" : "none";
}

function closeDropdowns() {
  document.getElementById("profilePanel").style.display = "none";
  document.getElementById("notifPanel").style.display   = "none";
}

// Close dropdowns on outside click
document.addEventListener("click", (e) => {
  const profilePanel = document.getElementById("profilePanel");
  const notifPanel   = document.getElementById("notifPanel");
  const avatar       = document.getElementById("userAvatar");
  const bell         = document.getElementById("bellBtn");
  if (!avatar.contains(e.target) && !profilePanel.contains(e.target)) profilePanel.style.display="none";
  if (!bell.contains(e.target)   && !notifPanel.contains(e.target))   notifPanel.style.display="none";
});

// Close modals on outside click
document.getElementById("ticketModal").addEventListener("click", function(e){
  if (e.target===this) closeModal();
});
document.getElementById("helpModal").addEventListener("click", function(e){
  if (e.target===this) closeHelpModal();
});
document.getElementById("changePasswordModal").addEventListener("click", function(e){
  if (e.target===this) closeChangePasswordModal();
});
document.getElementById("aiPredictionModal").addEventListener("click", function(e){
  if (e.target===this) closeAiPredictionModal(false);
});

/* ============================
   TOAST
============================= */
function showToast(type, title, msg) {
  const container = document.getElementById("toastContainer");
  const icons = { success:"fa-circle-check", error:"fa-circle-xmark", info:"fa-circle-info" };
  const id = "toast-" + Date.now();
  container.innerHTML += `
    <div class="toast ${type}" id="${id}">
      <div class="toast-icon"><i class="fa-solid ${icons[type]}"></i></div>
      <div class="toast-text">
        <div class="toast-title">${title}</div>
        <div class="toast-msg">${msg}</div>
      </div>
    </div>`;
  setTimeout(() => { const el=document.getElementById(id); if(el) el.remove(); }, 4500);
}

/* ============================
   LOGOUT
============================= */
function logout() {
  fetch('/api/logout', { method: 'POST' })
  .finally(() => {
    localStorage.removeItem("role");
    localStorage.removeItem("userEmail");
    window.location.href = "index.html";
  });
}

/* ============================
   CHANGE PASSWORD
============================= */
function openChangePasswordModal() {
  document.getElementById("changeCurrentPassword").value = "";
  document.getElementById("changeNewPassword").value = "";
  document.getElementById("changeConfirmPassword").value = "";
  document.getElementById("changePasswordErrorText").innerText = "";
  document.getElementById("changePasswordModal").classList.add("show");
}

function closeChangePasswordModal() {
  document.getElementById("changePasswordModal").classList.remove("show");
}

function submitChangePassword() {
  const current_password = document.getElementById("changeCurrentPassword").value;
  const new_password = document.getElementById("changeNewPassword").value;
  const confirm_password = document.getElementById("changeConfirmPassword").value;
  const errorText = document.getElementById("changePasswordErrorText");
  
  errorText.innerText = "";
  if (!current_password || !new_password || !confirm_password) {
    errorText.innerText = "Please fill in all fields.";
    return;
  }
  if (new_password.length < 6) {
    errorText.innerText = "New password must be at least 6 characters.";
    return;
  }
  if (new_password !== confirm_password) {
    errorText.innerText = "New passwords do not match.";
    return;
  }
  
  fetch('/api/me/change_password', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ current_password, new_password })
  })
  .then(response => response.json().then(data => ({ status: response.status, data })))
  .then(({ status, data }) => {
    if (status === 200 && data.success) {
      closeChangePasswordModal();
      showToast("success", "Password Updated", "Your password has been changed successfully.");
    } else {
      errorText.innerText = data.message || "Failed to update password.";
    }
  })
  .catch(err => {
    console.error(err);
    errorText.innerText = "Connection error. Please try again.";
  });
}

// Global cached ticket list from backend
let myTicketsList = [];

/* ============================
   INIT
============================= */
(function init() {
  initSidebarState();
  renderMyTickets(); // Automatically loads backend tickets and updates stats dynamically
  updateNotifBadge();
  renderNotifDropdown();

  const email = localStorage.getItem("userEmail") || "user@gmail.com";
  const letter = email.charAt(0).toUpperCase();
  const name   = email.split("@")[0];
  const userName = localStorage.getItem("userName") || name.charAt(0).toUpperCase() + name.slice(1);

  const profileImg = localStorage.getItem("userProfileImage_" + email);
  const avatarEl = document.getElementById("userAvatar");
  const iconLargeEl = document.getElementById("profileIconLarge");

  if (profileImg) {
    avatarEl.innerHTML = `<img src="${profileImg}" style="width: 100%; height: 100%; border-radius: 50%; object-fit: cover; display: block;">`;
    iconLargeEl.innerHTML = `<img src="${profileImg}" style="width: 100%; height: 100%; border-radius: 50%; object-fit: cover; display: block;">`;
  } else {
    avatarEl.innerText       = letter;
    iconLargeEl.innerText = letter;
  }
  document.getElementById("profileName").innerText      = userName;
  document.getElementById("profileEmail").innerText     = email;

  // Fetch updated profile data from database
  fetch('/api/me')
    .then(res => res.json())
    .then(data => {
      if (data.success && data.user) {
        const u = data.user;
        localStorage.setItem("userName", u.username);
        localStorage.setItem("userEmail", u.email);
        localStorage.setItem("userPhone", u.phone || "");
        localStorage.setItem("userProductsPurchased", u.products_purchased || "");
        
        document.getElementById("profileName").innerText = u.username;
        document.getElementById("profileEmail").innerText = u.email;
        
        const nameInput = document.getElementById("name");
        if (nameInput) nameInput.value = u.username;
        const emailInput = document.getElementById("email");
        if (emailInput) emailInput.value = u.email;
      }
    })
    .catch(err => console.error("Error loading profile info:", err));

  // Background auto-polling helper to fetch status updates and solver notes every 6 seconds
  setInterval(() => {
    const searchInput = document.getElementById("ticketSearch");
    const statusFilter = document.getElementById("statusFilter");
    const txt = searchInput ? searchInput.value : "";
    const stat = statusFilter ? statusFilter.value : "";
    
    const myTicketsSection = document.getElementById("section-mytickets");
    if (myTicketsSection && myTicketsSection.style.display === "block") {
      renderMyTickets(txt, stat);
    } else {
      fetch('/api/tickets')
      .then(response => response.json())
      .then(data => {
        if (data.success) {
          myTicketsList = data.tickets || [];
          updateStats(myTicketsList);
        }
      })
      .catch(err => console.error(err));
    }
  }, 6000);
})();

/* ============================
   EDIT PROFILE HANDLERS
============================= */
let tempProfileImageBase64 = null;

function openEditProfileModal() {
  const email = localStorage.getItem("userEmail") || "user@gmail.com";
  const name = localStorage.getItem("userName") || email.split("@")[0].charAt(0).toUpperCase() + email.split("@")[0].slice(1);
  const profileImg = localStorage.getItem("userProfileImage_" + email);

  document.getElementById("editProfileName").value = name;
  document.getElementById("editProfileEmail").value = email;
  document.getElementById("editProfilePhone").value = localStorage.getItem("userPhone") || "";
  const selectEl = document.getElementById("editProfileProduct");
  if (selectEl) {
    const purchasedArray = (localStorage.getItem("userProductsPurchased") || "").split(",").map(p => p.trim());
    Array.from(selectEl.options).forEach(opt => {
      opt.selected = purchasedArray.includes(opt.value);
    });
  }
  document.getElementById("editProfileErrorText").innerText = "";

  const letterSpan = document.getElementById("profileImagePreviewLetter");
  const imgEl = document.getElementById("profileImagePreviewImg");

  tempProfileImageBase64 = profileImg || null;

  if (profileImg) {
    imgEl.src = profileImg;
    imgEl.style.display = "block";
    letterSpan.style.display = "none";
  } else {
    letterSpan.innerText = name.charAt(0).toUpperCase();
    letterSpan.style.display = "block";
    imgEl.style.display = "none";
    imgEl.src = "";
  }

  document.getElementById("editProfileModal").classList.add("show");
}

function closeEditProfileModal() {
  document.getElementById("editProfileModal").classList.remove("show");
}

function handleProfileImageSelect(event) {
  const file = event.target.files[0];
  if (!file) return;

  const reader = new FileReader();
  reader.onload = function(e) {
    tempProfileImageBase64 = e.target.result;
    
    const letterSpan = document.getElementById("profileImagePreviewLetter");
    const imgEl = document.getElementById("profileImagePreviewImg");
    
    imgEl.src = tempProfileImageBase64;
    imgEl.style.display = "block";
    letterSpan.style.display = "none";
  };
  reader.readAsDataURL(file);
}

function submitEditProfile() {
  const username = document.getElementById("editProfileName").value.trim();
  const email = document.getElementById("editProfileEmail").value.trim();
  const phone = document.getElementById("editProfilePhone").value.trim();
  
  const selectEl = document.getElementById("editProfileProduct");
  let products_purchased = "";
  if (selectEl) {
    const selectedOptions = Array.from(selectEl.selectedOptions).map(opt => opt.value).filter(val => val !== "");
    products_purchased = selectedOptions.join(", ");
  }
  const errorText = document.getElementById("editProfileErrorText");

  errorText.innerText = "";
  if (!username || !email) {
    errorText.innerText = "Please fill in all fields.";
    return;
  }
  if (!email.includes("@")) {
    errorText.innerText = "Please enter a valid email address.";
    return;
  }

  fetch('/api/me/update', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, email, phone, products_purchased })
  })
  .then(response => response.json().then(data => ({ status: response.status, data })))
  .then(({ status, data }) => {
    if (status === 200 && data.success) {
      const oldEmail = localStorage.getItem("userEmail") || "user@gmail.com";
      localStorage.setItem("userName", username);
      localStorage.setItem("userEmail", email);
      localStorage.setItem("userPhone", phone);
      localStorage.setItem("userProductsPurchased", products_purchased);
      
      const oldKey = "userProfileImage_" + oldEmail;
      const newKey = "userProfileImage_" + email;
      
      if (tempProfileImageBase64) {
        localStorage.setItem(newKey, tempProfileImageBase64);
        if (oldKey !== newKey) {
          localStorage.removeItem(oldKey);
        }
      } else {
        localStorage.removeItem(newKey);
        if (oldKey !== newKey) {
          localStorage.removeItem(oldKey);
        }
      }

      // Update Topbar Avatar and dropdown card
      const avatarEl = document.getElementById("userAvatar");
      const iconLargeEl = document.getElementById("profileIconLarge");
      const letter = username.charAt(0).toUpperCase();

      if (tempProfileImageBase64) {
        avatarEl.innerHTML = `<img src="${tempProfileImageBase64}" style="width: 100%; height: 100%; border-radius: 50%; object-fit: cover; display: block;">`;
        iconLargeEl.innerHTML = `<img src="${tempProfileImageBase64}" style="width: 100%; height: 100%; border-radius: 50%; object-fit: cover; display: block;">`;
      } else {
        avatarEl.innerText = letter;
        iconLargeEl.innerText = letter;
      }

      document.getElementById("profileName").innerText = username;
      document.getElementById("profileEmail").innerText = email;

      // Update name inputs on Create Ticket form if present
      const nameInput = document.getElementById("name");
      if (nameInput) nameInput.value = username;
      const emailInput = document.getElementById("email");
      if (emailInput) emailInput.value = email;

      closeEditProfileModal();
      if (data.pending_approval) {
        showToast("success", "Profile Updated", "Your changes have been saved (pending admin approval).");
      } else {
        showToast("success", "Profile Updated", "Your profile details have been saved.");
      }
    } else {
      errorText.innerText = data.message || "Failed to update profile details.";
    }
  })
  .catch(err => {
    console.error(err);
    errorText.innerText = "Connection error. Please try again.";
  });
}

function deleteMyAccount() {
  if (!confirm("Are you sure you want to delete your account? This action is permanent and will delete your account immediately!")) {
    return;
  }
  
  fetch('/api/me/delete', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' }
  })
  .then(res => res.json())
  .then(data => {
    if (data.success) {
      const email = localStorage.getItem("userEmail") || "";
      localStorage.removeItem("role");
      localStorage.removeItem("userEmail");
      localStorage.removeItem("userName");
      localStorage.removeItem("userPhone");
      localStorage.removeItem("userProductsPurchased");
      localStorage.removeItem("userProfileImage_" + email);
      
      alert("Your account has been deleted successfully.");
      window.location.href = "index.html";
    } else {
      showToast("error", "Error Deleting Account", data.message || "Failed to delete account.");
    }
  })
  .catch(err => {
    console.error(err);
    showToast("error", "Connection Error", "Please try again.");
  });
}

/* ============================
   SIDEBAR TOGGLE & MINIMIZATION
============================= */
function toggleSidebar(minimize) {
  const sidebar = document.querySelector(".sidebar");
  const mainContent = document.querySelector(".main-content");
  const expandBtn = document.getElementById("sidebarExpandBtn");
  
  if (minimize) {
    if (sidebar) sidebar.classList.add("minimized");
    if (mainContent) mainContent.classList.add("expanded");
    if (expandBtn) expandBtn.style.display = "flex";
    localStorage.setItem("sidebarMinimized", "true");
  } else {
    if (sidebar) sidebar.classList.remove("minimized");
    if (mainContent) mainContent.classList.remove("expanded");
    if (expandBtn) expandBtn.style.display = "none";
    localStorage.setItem("sidebarMinimized", "false");
  }
}

function initSidebarState() {
  const isMinimized = localStorage.getItem("sidebarMinimized") === "true";
  toggleSidebar(isMinimized);
}

/* ============================
   PROFILE PHOTO REMOVAL
============================= */
function removeProfilePhoto() {
  tempProfileImageBase64 = null;
  const letterSpan = document.getElementById("profileImagePreviewLetter");
  const imgEl = document.getElementById("profileImagePreviewImg");
  const username = document.getElementById("editProfileName").value.trim() || "U";
  
  if (letterSpan) {
    letterSpan.innerText = username.charAt(0).toUpperCase();
    letterSpan.style.display = "block";
  }
  if (imgEl) {
    imgEl.src = "";
    imgEl.style.display = "none";
  }
}
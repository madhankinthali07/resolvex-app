//app.js

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
    return originalFetch(url, options);
  };
})();

let currentRole = "";

const CREDENTIALS = {
  admin:  { email:"admin@gmail.com",  password:"admin123",  page:"dashboard-admin.html"  },
  solver: { email:"solver@gmail.com", password:"solver123", page:"dashboard-solver.html" },
};

const HINTS = {
  admin:  "Monitor support operations & AI analytics",
  user:   "Raise support requests and track progress",
  solver: "Handle assigned tickets and resolve issues"
};
const ICONS = {
  admin:"fa-user-shield", user:"fa-user", solver:"fa-headset"
};

/* ============================
   OPEN LOGIN
============================= */
function openRoleSelector() {
  selectRoleAndRegister('user');
}

function closeRoleSelector() {
  document.getElementById("roleSelectorModal").style.display = "none";
}

function selectRoleAndRegister(role) {
  closeRoleSelector();
  currentRole = role;
  openRegister();
}

/* ============================
   LOGIN
============================= */
function login() {
  const email    = document.getElementById("email").value.trim();
  const password = document.getElementById("password").value;
  const error    = document.getElementById("errorText");
  const btn      = document.getElementById("loginBtn");

  error.innerText = "";
  if (!email || !password) { error.innerText = "Please fill in all fields."; return; }

  btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Logging in...';

  fetch('/api/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password })
  })
  .then(response => response.json().then(data => ({ status: response.status, data })))
  .then(({ status, data }) => {
    if (status === 200 && data.success) {
      localStorage.setItem("role", data.user.role);
      localStorage.setItem("userEmail", data.user.email);
      localStorage.setItem("userName", data.user.username);
      
      const pages = {
        user: "dashboard-user.html",
        solver: "dashboard-solver.html",
        admin: "dashboard-admin.html"
      };
      
      window.location.href = pages[data.user.role];
    } else {
      error.innerText = data.message || "Invalid email or password.";
      btn.innerHTML   = '<span>Login</span><i class="fa-solid fa-arrow-right"></i>';
    }
  })
  .catch(err => {
    console.error(err);
    error.innerText = "Connection error. Please try again.";
    btn.innerHTML   = '<span>Login</span><i class="fa-solid fa-arrow-right"></i>';
  });
}

/* ============================
   REGISTER
============================= */
function openRegister() {
  document.getElementById("registerModal").style.display = "flex";
  document.getElementById("regErrorText").style.color    = "#ef4444";
  document.getElementById("regErrorText").innerText      = "";
  ["reg-name","reg-email","reg-password","reg-confirm"].forEach(id => {
    document.getElementById(id).value = "";
  });

  // Customise register title and hint based on currentRole
  const roleName = currentRole === 'user' ? 'Customer' : currentRole.charAt(0).toUpperCase() + currentRole.slice(1);
  document.querySelector("#registerModal h2").innerText = `Create ${roleName} Account`;
  
  const hints = {
    user: "Sign up to raise and track support tickets",
    solver: "Register to join the support engineering team",
    admin: "Register a new systems administrator account"
  };
  document.querySelector("#registerModal .login-hint").innerText = hints[currentRole] || "Create a new portal account";

  // Dynamic admin authorization display
  if (currentRole === "admin") {
    document.getElementById("adminAuthFields").style.display = "block";
    document.getElementById("default-admin-username").value = "";
    document.getElementById("default-admin-password").value = "";
  } else {
    document.getElementById("adminAuthFields").style.display = "none";
  }
}

function closeRegister() {
  document.getElementById("registerModal").style.display = "none";
}

function register() {
  const name     = document.getElementById("reg-name").value.trim();
  const email    = document.getElementById("reg-email").value.trim();
  const password = document.getElementById("reg-password").value;
  const confirm  = document.getElementById("reg-confirm").value;
  const error    = document.getElementById("regErrorText");
  const btn      = document.getElementById("registerBtn");

  error.innerText = "";

  if (!name || !email || !password || !confirm) {
    error.innerText = "Please fill in all fields."; return;
  }
  if (!email.includes("@")) {
    error.innerText = "Please enter a valid email address."; return;
  }
  if (password.length < 6) {
    error.innerText = "Password must be at least 6 characters."; return;
  }
  if (password !== confirm) {
    error.innerText = "Passwords do not match."; return;
  }

  const payload = { username: name, email, password, role: currentRole };
  
  if (currentRole === "admin") {
    const defAdminUser = document.getElementById("default-admin-username").value.trim();
    const defAdminPass = document.getElementById("default-admin-password").value;
    if (!defAdminUser || !defAdminPass) {
      error.style.color = "#ef4444";
      error.innerText = "Please authenticate with default admin credentials.";
      return;
    }
    payload.default_admin_username = defAdminUser;
    payload.default_admin_password = defAdminPass;
  }

  btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Creating...';

  fetch('/api/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  })
  .then(response => response.json().then(data => ({ status: response.status, data })))
  .then(({ status, data }) => {
    if (status === 200 && data.success) {
      if (data.pending_approval) {
        error.style.color = "#22c55e";
        error.innerText = "Request submitted successfully! Your account is pending administrator approval before you can log in.";
        btn.style.display = "none";
        setTimeout(() => {
          closeRegister();
          btn.style.display = "block";
          btn.innerHTML = '<span>Create Account</span><i class="fa-solid fa-arrow-right"></i>';
        }, 5000);
        return;
      }
      
      localStorage.setItem("role", data.user.role);
      localStorage.setItem("userEmail", data.user.email);
      localStorage.setItem("userName", data.user.username);
      
      const pages = {
        user: "dashboard-user.html",
        solver: "dashboard-solver.html",
        admin: "dashboard-admin.html"
      };
      
      window.location.href = pages[data.user.role];
    } else {
      error.style.color = "#ef4444";
      error.innerText = data.message || "Registration failed.";
      btn.innerHTML   = '<span>Create Account</span><i class="fa-solid fa-arrow-right"></i>';
    }
  })
  .catch(err => {
    console.error(err);
    error.innerText = "Connection error. Please try again.";
    btn.innerHTML   = '<span>Create Account</span><i class="fa-solid fa-arrow-right"></i>';
  });
}

/* ============================
   KEYBOARD & OUTSIDE CLICK
============================= */
document.addEventListener("keydown", (e) => {
  if (e.key !== "Enter") return;
  if (document.getElementById("registerModal").style.display === "flex") {
    register();
  } else if (document.getElementById("roleSelectorModal").style.display === "flex") {
    // Role selector is active, don't auto-login
  } else {
    login();
  }
});

document.getElementById("roleSelectorModal").addEventListener("click", function(e) {
  if (e.target===this) closeRoleSelector();
});
document.getElementById("registerModal").addEventListener("click", function(e) {
  if (e.target===this) closeRegister();
});

// Dynamic load for actual tickets managed count on index page
document.addEventListener("DOMContentLoaded", () => {
  const countEl = document.getElementById("ticketsManagedCount");
  if (countEl) {
    fetch('/api/public/stats')
      .then(res => res.json())
      .then(data => {
        if (data && typeof data.totalTickets !== 'undefined') {
          countEl.innerText = data.totalTickets;
        }
      })
      .catch(err => console.error("Error loading tickets managed count:", err));
  }
});
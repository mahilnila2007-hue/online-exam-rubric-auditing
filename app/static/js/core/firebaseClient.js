/**
 * Modular Firebase Web SDK Auth client.
 * Uses strictly public Firebase Web config (no admin credentials ever reach the browser).
 */

import { initializeApp, getApps } from "https://www.gstatic.com/firebasejs/10.14.1/firebase-app.js";
import {
  getAuth,
  connectAuthEmulator,
  signInWithEmailAndPassword,
  createUserWithEmailAndPassword,
  updateProfile,
  sendPasswordResetEmail,
  signOut,
} from "https://www.gstatic.com/firebasejs/10.14.1/firebase-auth.js";

let cachedAuth = null;

function readEmbeddedConfig() {
  const script = document.getElementById("firebase-web-config");
  if (!script) return null;
  try {
    return JSON.parse(script.textContent || "{}");
  } catch {
    return null;
  }
}

export async function getFirebaseClientAuth() {
  if (cachedAuth) return cachedAuth;

  let cfg = readEmbeddedConfig();
  if (!cfg || !cfg.apiKey) {
    const res = await fetch("/api/auth/client-config", { credentials: "same-origin" });
    const data = await res.json();
    cfg = data?.data?.firebase || {};
  }

  const emulatorHost = cfg.authEmulatorHost || "";
  const isConfigured = Boolean(
    emulatorHost || (cfg.apiKey && !cfg.apiKey.startsWith("your-") && cfg.projectId && !cfg.projectId.startsWith("your-"))
  );

  if (!isConfigured) {
    throw new Error(
      "Firebase Web SDK is not configured. Populate FIREBASE_WEB_* variables in your .env file."
    );
  }

  const firebaseConfig = {
    apiKey: cfg.apiKey || "demo-api-key",
    authDomain: cfg.authDomain || `${cfg.projectId || "demo-project"}.firebaseapp.com`,
    projectId: cfg.projectId || "demo-project",
    storageBucket: cfg.storageBucket || "",
    messagingSenderId: cfg.messagingSenderId || "",
    appId: cfg.appId || "",
    ...(cfg.measurementId ? { measurementId: cfg.measurementId } : {}),
  };

  const app = getApps().length ? getApps()[0] : initializeApp(firebaseConfig);
  const auth = getAuth(app);

  if (emulatorHost) {
    const url = emulatorHost.startsWith("http") ? emulatorHost : `http://${emulatorHost}`;
    connectAuthEmulator(auth, url, { disableWarnings: true });
  }

  cachedAuth = auth;
  return auth;
}

export async function firebaseSignIn(email, password) {
  const auth = await getFirebaseClientAuth();
  const credential = await signInWithEmailAndPassword(auth, email, password);
  const idToken = await credential.user.getIdToken(true);
  return { user: credential.user, idToken };
}

export async function firebaseRegister(email, password, displayName) {
  const auth = await getFirebaseClientAuth();
  const credential = await createUserWithEmailAndPassword(auth, email, password);
  if (displayName) {
    await updateProfile(credential.user, { displayName });
  }
  const idToken = await credential.user.getIdToken(true);
  return { user: credential.user, idToken };
}

export async function firebasePasswordReset(email) {
  const auth = await getFirebaseClientAuth();
  await sendPasswordResetEmail(auth, email);
}

export async function firebaseClientSignOut() {
  try {
    const auth = await getFirebaseClientAuth();
    await signOut(auth);
  } catch {
    // Ignore if Firebase wasn't initialized
  }
}


package com.owlbutcherlive.afk.core.security

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

/**
 * Persists sensitive credentials via EncryptedSharedPreferences.
 *
 * The encryption master key is stored in Android Keystore (non-exportable,
 * AES-256 GCM). Secret values — passwords, private keys, passphrases —
 * are stored as encrypted preference values (AES-256 GCM content,
 * AES-256 SIV key names, both scoped to the Keystore-protected master key).
 *
 * Non-sensitive connection metadata (host, port, username, UI preferences)
 * is stored in regular SharedPreferences.
 *
 * This is NOT "secrets in Android Keystore" — the Keystore holds the key,
 * not the secrets themselves. The description above is the accurate model.
 */
class SecretStorage(context: Context) {

    companion object {
        private const val PREFS_SECURE = "afk_secure_prefs"
        private const val PREFS_PLAIN = "afk_plain_prefs"
        private const val KEY_PASSWORD = "ssh_password"
        private const val KEY_PRIVATE_KEY = "ssh_private_key"
        private const val KEY_PASSPHRASE = "ssh_key_passphrase"
        private const val KEY_HOST = "saved_host"
        private const val KEY_PORT = "saved_port"
        private const val KEY_USERNAME = "saved_username"
        private const val KEY_AUTH_MODE = "saved_auth_mode"
        private const val KEY_REMOTE_API_PORT = "saved_remote_api_port"
        private const val KEY_LOCAL_FORWARD_PORT = "saved_local_forward_port"
    }

    private val securePrefs: SharedPreferences by lazy {
        val masterKey = MasterKey.Builder(context)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()

        EncryptedSharedPreferences.create(
            context,
            PREFS_SECURE,
            masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
        )
    }

    private val plainPrefs: SharedPreferences by lazy {
        context.getSharedPreferences(PREFS_PLAIN, Context.MODE_PRIVATE)
    }

    // --- Secure secrets ---

    fun savePassword(password: String) {
        securePrefs.edit().putString(KEY_PASSWORD, password).apply()
    }

    fun getPassword(): String? = securePrefs.getString(KEY_PASSWORD, null)

    fun savePrivateKey(key: String) {
        securePrefs.edit().putString(KEY_PRIVATE_KEY, key).apply()
    }

    fun getPrivateKey(): String? = securePrefs.getString(KEY_PRIVATE_KEY, null)

    fun savePrivateKeyPassphrase(passphrase: String) {
        securePrefs.edit().putString(KEY_PASSPHRASE, passphrase).apply()
    }

    fun getPrivateKeyPassphrase(): String? = securePrefs.getString(KEY_PASSPHRASE, null)

    // --- Non-sensitive config ---

    fun saveHost(host: String) {
        plainPrefs.edit().putString(KEY_HOST, host).apply()
    }

    fun getHost(): String? = plainPrefs.getString(KEY_HOST, null)

    fun savePort(port: Int) {
        plainPrefs.edit().putInt(KEY_PORT, port).apply()
    }

    fun getPort(): Int = plainPrefs.getInt(KEY_PORT, 22)

    fun saveUsername(username: String) {
        plainPrefs.edit().putString(KEY_USERNAME, username).apply()
    }

    fun getUsername(): String? = plainPrefs.getString(KEY_USERNAME, null)

    fun saveAuthMode(mode: String) {
        plainPrefs.edit().putString(KEY_AUTH_MODE, mode).apply()
    }

    fun getAuthMode(): String? = plainPrefs.getString(KEY_AUTH_MODE, null)

    fun saveRemoteApiPort(port: Int) {
        plainPrefs.edit().putInt(KEY_REMOTE_API_PORT, port).apply()
    }

    fun getRemoteApiPort(): Int = plainPrefs.getInt(KEY_REMOTE_API_PORT, 3344)

    fun saveLocalForwardPort(port: Int) {
        plainPrefs.edit().putInt(KEY_LOCAL_FORWARD_PORT, port).apply()
    }

    fun getLocalForwardPort(): Int = plainPrefs.getInt(KEY_LOCAL_FORWARD_PORT, 3344)

    // --- Clear all ---

    fun clearAll() {
        securePrefs.edit().clear().apply()
        plainPrefs.edit().clear().apply()
    }
}

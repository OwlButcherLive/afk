package com.owlbutcherlive.afk.data

import android.content.Context
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken
import com.owlbutcherlive.afk.domain.ChatMessage
import java.io.File

/**
 * Minimal local cache for chat state that survives ViewModel/process death.
 *
 * Keeps a snapshot of recent messages and the input draft so the user
 * doesn't lose context when navigating away or if the app is recreated.
 *
 * Messages are stored with an associated sessionId to prevent cross-session
 * message leaks when the user switches between conversations.
 */
class ChatCache(context: Context) {

    private val cacheDir = File(context.filesDir, "chat_cache")
    private val messagesFile = File(cacheDir, "messages.json")
    private val sessionIdFile = File(cacheDir, "cached_session_id.txt")
    private val draftFile = File(cacheDir, "input_draft.txt")

    private val gson = Gson()

    init {
        cacheDir.mkdirs()
    }

    /**
     * Returns the sessionId associated with the currently cached messages,
     * or empty string if no session was cached.
     */
    fun getCachedSessionId(): String {
        if (!sessionIdFile.exists()) return ""
        return try {
            sessionIdFile.readText().trim()
        } catch (_: Exception) {
            ""
        }
    }

    /**
     * Loads cached messages. Returns empty list if no cache exists.
     * Messages may be from a different session — call [getCachedSessionId] to check.
     */
    fun loadMessages(): List<ChatMessage> {
        if (!messagesFile.exists()) return emptyList()
        return try {
            val json = messagesFile.readText()
            val type = object : TypeToken<List<ChatMessage>>() {}.type
            gson.fromJson(json, type) ?: emptyList()
        } catch (e: Exception) {
            messagesFile.delete()
            emptyList()
        }
    }

    /**
     * Saves messages with their associated sessionId.
     * The sessionId is stored separately so [getCachedSessionId] can be used
     * to detect cross-session cache mismatches on restore.
     */
    fun saveMessages(messages: List<ChatMessage>, forSessionId: String = "") {
        try {
            val json = gson.toJson(messages)
            messagesFile.writeText(json)
            if (forSessionId.isNotEmpty()) {
                sessionIdFile.writeText(forSessionId)
            }
        } catch (_: Exception) {
            // non-critical — server is source of truth
        }
    }

    /**
     * Returns true if cached messages belong to the given sessionId,
     * or if no session has been cached yet (first launch).
     */
    fun matchesSession(sessionId: String): Boolean {
        if (sessionId.isEmpty()) return true
        if (!sessionIdFile.exists()) return true
        return try {
            sessionIdFile.readText().trim() == sessionId
        } catch (_: Exception) {
            true
        }
    }

    fun loadDraft(): String {
        if (!draftFile.exists()) return ""
        return try {
            draftFile.readText()
        } catch (_: Exception) {
            ""
        }
    }

    fun saveDraft(text: String) {
        try {
            if (text.isEmpty()) {
                draftFile.delete()
            } else {
                draftFile.writeText(text)
            }
        } catch (_: Exception) {
            // non-critical
        }
    }

    fun clear() {
        messagesFile.delete()
        sessionIdFile.delete()
        draftFile.delete()
    }
}

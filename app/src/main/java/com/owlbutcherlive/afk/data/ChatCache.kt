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
 */
class ChatCache(context: Context) {

    private val cacheDir = File(context.filesDir, "chat_cache")
    private val messagesFile = File(cacheDir, "messages.json")
    private val draftFile = File(cacheDir, "input_draft.txt")

    private val gson = Gson()

    init {
        cacheDir.mkdirs()
    }

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

    fun saveMessages(messages: List<ChatMessage>) {
        try {
            val json = gson.toJson(messages)
            messagesFile.writeText(json)
        } catch (_: Exception) {
            // non-critical — server is source of truth
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
        draftFile.delete()
    }
}

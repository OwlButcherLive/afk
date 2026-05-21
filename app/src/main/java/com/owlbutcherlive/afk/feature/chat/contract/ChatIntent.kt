package com.owlbutcherlive.afk.feature.chat.contract

sealed interface ChatIntent {
    data class UpdateInput(val text: String) : ChatIntent
    data object SendMessage : ChatIntent
    data object Reconnect : ChatIntent
    data object RetryLoadHistory : ChatIntent
    data object ScreenResumed : ChatIntent
    data object DismissError : ChatIntent
    data class LoadSession(
        val sessionId: String,
        val sessionTitle: String,
        val agentId: String = ""
    ) : ChatIntent
    data object NavigateBack : ChatIntent
}

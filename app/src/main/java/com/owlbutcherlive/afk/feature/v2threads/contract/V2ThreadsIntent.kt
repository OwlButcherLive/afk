package com.owlbutcherlive.afk.feature.v2threads.contract

sealed interface V2ThreadsIntent {
    data object LoadThreads : V2ThreadsIntent
    data class OpenThread(val threadId: String, val title: String) : V2ThreadsIntent
    data class SendMessage(val text: String) : V2ThreadsIntent
    data object ConnectWs : V2ThreadsIntent
    data object Disconnect : V2ThreadsIntent
    data object ToggleDebug : V2ThreadsIntent
    data object Refresh : V2ThreadsIntent
}

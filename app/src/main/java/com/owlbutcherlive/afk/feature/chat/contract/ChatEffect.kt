package com.owlbutcherlive.afk.feature.chat.contract

sealed interface ChatEffect {
    data object NavigateBack : ChatEffect
    data class Error(val message: String) : ChatEffect
}

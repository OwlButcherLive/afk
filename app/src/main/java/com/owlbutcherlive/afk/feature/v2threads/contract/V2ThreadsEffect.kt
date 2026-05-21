package com.owlbutcherlive.afk.feature.v2threads.contract

sealed interface V2ThreadsEffect {
    data class ShowToast(val message: String) : V2ThreadsEffect
    data class ShowError(val error: String) : V2ThreadsEffect
}

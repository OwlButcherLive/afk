package com.owlbutcherlive.afk

import android.app.Application

class AfkApplication : Application() {
    object V2Config {
        var enabled = false
    }

    override fun onCreate() {
        super.onCreate()
    }
}

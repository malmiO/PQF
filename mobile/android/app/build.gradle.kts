import java.util.Properties
import java.io.FileInputStream

plugins {
    id("com.android.application")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

// Release signing is read from android/key.properties, which is NOT in the
// repository (listed in android/.gitignore). The keystore itself lives OUTSIDE
// the repository. There is NO debug-key fallback for release: a release build
// without key.properties fails with a clear message, so an APK signed with the
// debug key can never be produced by accident. Debug builds are unaffected.
val keystoreProperties = Properties()
val keystorePropertiesFile = rootProject.file("key.properties")
val hasReleaseSigning = keystorePropertiesFile.exists()
if (hasReleaseSigning) {
    keystoreProperties.load(FileInputStream(keystorePropertiesFile))
}

android {
    namespace = "com.eclat.pqf"
    compileSdk = 36
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        // Public application id. This can never change after the first release.
        applicationId = "com.eclat.pqf"
        // Android 10 is the lowest version being certified (Samsung J6+).
        minSdk = 29
        // Google Play requires API 36 for new apps from 31 Aug 2026.
        targetSdk = 36
        // Uses the version code from pubspec.yaml. When using split APKs, 1000 * ABI_VERSION
        // is added automatically by Flutter. (https://developer.android.com/studio/build/configure-apk-splits#configure-APK-versions)
        // You can force using the value of versionCode by specifying the `-P force-version-code-ignoring-abi=true`
        // flag during build.
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    signingConfigs {
        if (hasReleaseSigning) {
            create("release") {
                keyAlias = keystoreProperties["keyAlias"] as String?
                keyPassword = keystoreProperties["keyPassword"] as String?
                storeFile = (keystoreProperties["storeFile"] as String?)?.let { file(it) }
                storePassword = keystoreProperties["storePassword"] as String?
            }
        }
    }

    buildTypes {
        release {
            // Sign only with the upload keystore when it is configured. There is
            // NO debug-key fallback; a release build without signing fails below
            // (guarded in the task graph so debug builds are unaffected).
            if (hasReleaseSigning) {
                signingConfig = signingConfigs.getByName("release")
            }
        }
    }
}

// Fail a RELEASE build that has no upload keystore, rather than letting it be
// signed with the debug key. Checked only when a release/bundle task actually
// runs, so `assembleDebug` and `flutter run` are never affected.
gradle.taskGraph.whenReady {
    val wantsRelease = allTasks.any {
        val n = it.name
        (n.contains("Release") || n.contains("ReleaseBundle") || n.endsWith("Release")) &&
            (n.startsWith("assemble") || n.startsWith("bundle") || n.startsWith("package"))
    }
    if (wantsRelease && !hasReleaseSigning) {
        throw GradleException(
            "Release build requires android/key.properties and the upload " +
            "keystore it points to, which are missing. Create them, then " +
            "rebuild. There is no debug-key fallback for release. " +
            "(Debug builds are unaffected.)"
        )
    }
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

flutter {
    source = "../.."
}

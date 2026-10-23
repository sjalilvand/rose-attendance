# Retrofit + kotlinx-serialization keep DTOs reflectively-free, but keep the
# generated serializers just in case R8 looks for them by name.
-keepattributes *Annotation*, InnerClasses
-dontnote kotlinx.serialization.AnnotationsKt

-keepclassmembers class ir.rose.attendance.data.** {
    *** Companion;
}
-keepclasseswithmembers class ir.rose.attendance.data.** {
    kotlinx.serialization.KSerializer serializer(...);
}

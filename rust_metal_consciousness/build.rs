fn main() {
    pyo3_build_config::add_extension_module_link_args();

    // Link Metal framework
    #[cfg(target_os = "macos")]
    {
        println!("cargo:rustc-link-lib=framework=Metal");
        println!("cargo:rustc-link-lib=framework=MetalKit");
        println!("cargo:rustc-link-lib=framework=CoreGraphics");
    }
}
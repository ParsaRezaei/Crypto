use rand::Rng;
use primal::is_prime;
use std::io::{self, Write};
use std::time::{Duration, Instant};
use sysinfo::{Pid, System, RefreshKind, ProcessRefreshKind};

fn main() {
    let mut system = System::new_all();
    system.refresh_all();
    let pid = Pid::from(std::process::id() as usize);

    // Ask for prime generation method
    println!("Choose prime generation method:\n  0: All methods\n  1: Random Prime\n  2: Primal Package");
    let choice = get_user_input_choice();

    // Get the number of iterations
    print!("Enter the number of iterations (n): ");
    io::stdout().flush().unwrap();
    let n = get_user_input_iterations();

    let refresh_kind = RefreshKind::new().with_processes(ProcessRefreshKind::new().with_memory());

    let mut overall_times: Vec<Duration> = Vec::new();
    let mut overall_memories: Vec<u64> = Vec::new();

    // Function pointer for prime generation based on user choice
    let generate_prime: Box<dyn Fn(usize) -> u64> = match choice {
        1 => Box::new(generate_random_prime),
        2 => Box::new(|i| generate_prime_primal(i + 1)),
        _ => {
            // Run all methods if choice is 0
            println!("\nRunning all methods for {} iterations each...\n", n);

            // Run each method `n` times and accumulate statistics
            let (times1, memories1) = run_method(n, &mut system, pid, refresh_kind.clone(), "Random Prime", generate_random_prime);
            let (times2, memories2) = run_method(n, &mut system, pid, refresh_kind.clone(), "Primal Package", |i| generate_prime_primal(i + 1));

            // Display summary statistics for each method
            display_summary_statistics("Random Prime", &times1, &memories1, system.total_memory());
            display_summary_statistics("Primal Package", &times2, &memories2, system.total_memory());

            // Store all times and memory usages for final comparison
            overall_times.extend(&times1);
            overall_times.extend(&times2);
            overall_memories.extend(&memories1);
            overall_memories.extend(&memories2);

            // Display overall comparison between methods
            display_comparison_summary(&times1, &memories1, &times2, &memories2, n, system.total_memory());

            return;
        }
    };

    // Run the selected method `n` times
    run_method(n, &mut system, pid, refresh_kind, match choice {
        1 => "Random Prime",
        2 => "Primal Package",
        _ => unreachable!(),
    }, generate_prime);
}

/// Runs the specified prime generation method `n` times and records statistics, returning the times and memory usages.
fn run_method<F>(n: usize, system: &mut System, pid: Pid, refresh_kind: RefreshKind, method_name: &str, generate_prime: F) -> (Vec<Duration>, Vec<u64>)
where
    F: Fn(usize) -> u64,
{
    let mut times = Vec::with_capacity(n);
    let mut memories = Vec::with_capacity(n);

    println!("\nStarting {} for {} iterations...\n", method_name, n);

    for i in 0..n {
        system.refresh_specifics(refresh_kind.clone());
        let mem_before = system.process(pid).map_or(0, |proc| proc.memory());

        let start_time = Instant::now();
        let prime = generate_prime(i);
        let duration = start_time.elapsed();

        system.refresh_specifics(refresh_kind.clone());
        let mem_after = system.process(pid).map_or(0, |proc| proc.memory());
        let mem_used = mem_after.saturating_sub(mem_before);

        times.push(duration);
        memories.push(mem_used);

        println!(
            "Iteration {:>3}: Prime = {:<20} | Time = {:?} | Memory Used = {} KB",
            i + 1,
            prime,
            duration,
            mem_used
        );
    }

    (times, memories)
}

/// Displays summary statistics for a given method.
fn display_summary_statistics(method_name: &str, times: &[Duration], memories: &[u64], total_system_memory: u64) {
    let total_time: Duration = times.iter().sum();
    let avg_time = total_time / (times.len() as u32);
    let total_memory: u64 = memories.iter().sum();
    let avg_memory = total_memory / (memories.len() as u64);

    println!("\n=== {} Statistics ===", method_name);
    println!("Total Iterations: {}", times.len());
    println!("Total Time: {:?}, Average Time: {:?}", total_time, avg_time);
    println!("Memory Used (Total): {} KB, (Average): {} KB", total_memory, avg_memory);
    println!("System Total Memory: {} KB, Used Memory Percentage: {:.2}%", total_system_memory, (total_memory as f64 / total_system_memory as f64) * 100.0);
}

/// Displays a final comparison between two methods, showing differences in time and memory usage.
fn display_comparison_summary(
    times1: &[Duration],
    memories1: &[u64],
    times2: &[Duration],
    memories2: &[u64],
    n: usize,
    total_system_memory: u64,
) {
    // Calculate total and average time/memory for both methods
    let total_time1: Duration = times1.iter().sum();
    let avg_time1 = total_time1 / (times1.len() as u32);
    let total_memory1: u64 = memories1.iter().sum();
    let avg_memory1 = total_memory1 / (memories1.len() as u64);

    let total_time2: Duration = times2.iter().sum();
    let avg_time2 = total_time2 / (times2.len() as u32);
    let total_memory2: u64 = memories2.iter().sum();
    let avg_memory2 = total_memory2 / (memories2.len() as u64);

    println!("\n=== Comparison Summary ===");
    println!("Total Iterations per Method: {}", n);
    println!("\nRandom Prime Method:");
    println!("  Total Time: {:?}, Average Time: {:?}", total_time1, avg_time1);
    println!("  Total Memory Used: {} KB, Average Memory Used: {} KB", total_memory1, avg_memory1);

    println!("\nPrimal Package Method:");
    println!("  Total Time: {:?}, Average Time: {:?}", total_time2, avg_time2);
    println!("  Total Memory Used: {} KB, Average Memory Used: {} KB", total_memory2, avg_memory2);

    // Display resource usage differences
    println!("\n=== Resource Usage Differences ===");
    println!("Time Difference (Total): {:?}", total_time1.checked_sub(total_time2).unwrap_or_else(|| total_time2 - total_time1));
    println!("Time Difference (Average per Iteration): {:?}", avg_time1.checked_sub(avg_time2).unwrap_or_else(|| avg_time2 - avg_time1));

    println!(
        "Memory Difference (Total): {} KB",
        total_memory1.saturating_sub(total_memory2)
    );
    println!(
        "Memory Difference (Average per Iteration): {} KB",
        avg_memory1.saturating_sub(avg_memory2)
    );

    println!("\nSystem Total Memory: {} KB", total_system_memory);
}

/// Gets a user input choice for the prime generation method.
fn get_user_input_choice() -> u8 {
    let mut input = String::new();
    io::stdin().read_line(&mut input).expect("Failed to read line");
    input.trim().parse().unwrap_or(0)
}

/// Gets the number of iterations as input.
fn get_user_input_iterations() -> usize {
    let mut input = String::new();
    io::stdin().read_line(&mut input).expect("Failed to read line");
    input.trim().parse().unwrap_or(1)
}

/// Generates a random prime number by generating random numbers and checking if they're prime.
fn generate_random_prime(_: usize) -> u64 {
    let mut rng = rand::thread_rng();
    loop {
        let num = rng.gen_range(2..=1_000_000);
        if is_prime(num) {
            return num;
        }
    }
}

/// Generates the nth prime using the `primal` crate.
fn generate_prime_primal(n: usize) -> u64 {
    primal::Primes::all().nth(n).unwrap_or(2) as u64
}
